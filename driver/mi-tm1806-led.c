// SPDX-License-Identifier: MIT OR GPL-2.0
/*
 * mi-tm1806-led.c -- 4-zone RGB keyboard backlight driver for the
 * Xiaomi Mi Gaming Laptop (TIMI TM1806, 2019).
 *
 * Each zone is exposed as a multicolor LED classdev:
 *   /sys/class/leds/mi_tm1806::kbd_{bar,left,mid,right}/multi_intensity
 *   /sys/class/leds/mi_tm1806::kbd_{bar,left,mid,right}/brightness
 *
 * Global controls live as device attributes on the WMI device
 * (/sys/bus/wmi/devices/E2A89D40-.../):
 *   effect             1=static 2=breath 3=wave 4=colorful
 *   speed              0..2 (0=slow, 2=fast)
 *   secondary_color    rrggbb hex, used as second color in colorful (LETY=4)
 *   panel_brightness   0..5 (0=max, 5=off; KBBR sentinel)
 *
 * Cold-boot constraint: if KBBR=5 at boot the panel is power-gated and
 * software cannot wake it; the user must press Fn+brightness once. After
 * that all paints are silent (no Fn required).
 *
 * Mechanism: FB00/0101 SetColour stages C-registers, FB00/0100
 * SetLightEffect on LEDZ=04..07 triggers paint from C0Z. We pass
 * LEBR=current_KBBR (read live from \_SB_.PCI0.LPCB.EC0.KBBR) so the
 * painter does not blank the panel. Animated modes (LETY != 1) do not
 * refresh from C-registers, so each paint is a static prepass followed
 * by a mode-switch LightEffect.
 *
 * Brightness model: STORE-AND-COMMIT.
 * Writing to multi_intensity or brightness on any zone ONLY stores the
 * colour in memory — no WSAA calls are issued.  To push all pending
 * colours to the EC (and thus to the keyboard), write 1 to:
 *   /sys/bus/wmi/devices/E2A89D40-.../commit
 * This batch-paints all 4 zones in a single atomic cycle: one KBBR read,
 * one or two C-reg stages, then LightEffect triggers for every zone.
 * Because the entire commit runs under one mutex with no interleaved
 * userspace round-trips, the zones update virtually simultaneously,
 * eliminating the sequential wipe that caused visible flicker before.
 */

#include <dt-bindings/leds/common.h>
#include <linux/acpi.h>
#include <linux/led-class-multicolor.h>
#include <linux/leds.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/wmi.h>

#define WSAA_GUID  "E2A89D40-784F-4E91-BE22-AE373CDEA97A"
#define KBBR_PATH  "\\_SB_.PCI0.LPCB.EC0.KBBR"
#define WSAA_BUFLEN 32

#define LETY_STATIC   0x01
#define LETY_BREATH   0x02
#define LETY_WAVE     0x03
#define LETY_COLORFUL 0x04

/* DT2A: 1..8 selects C0Z..C7Z. Only C0Z (paint source) and C1Z
 * (colorful's second color) are functionally meaningful. */
#define DT2A_C0Z 0x01
#define DT2A_C1Z 0x02

#define NUM_ZONES 4

struct mi_zone {
	struct led_classdev_mc mc;
	struct mc_subled subleds[3];
	u8 ledz;
	const char *name;
};

struct mi_tm {
	struct wmi_device *wdev;
	struct mutex lock;
	u8 effect;
	u8 speed;
	u8 sec_r, sec_g, sec_b;
	struct mi_zone zones[NUM_ZONES];
};

static const struct {
	u8 ledz;
	const char *name;
} mi_zone_defs[NUM_ZONES] = {
	{ 0x04, "bar"   },
	{ 0x05, "left"  },
	{ 0x06, "mid"   },
	{ 0x07, "right" },
};

static int mi_read_kbbr(u8 *out)
{
	unsigned long long val;
	acpi_status s;

	s = acpi_evaluate_integer(NULL, (acpi_string)KBBR_PATH, NULL, &val);
	if (ACPI_FAILURE(s))
		return -EIO;
	*out = val & 0xff;
	return 0;
}

static int mi_wsaa(struct mi_tm *m, const u8 *buf)
{
	struct acpi_buffer ab = { WSAA_BUFLEN, (void *)buf };
	acpi_status s;

	s = wmidev_block_set(m->wdev, 0, &ab);
	return ACPI_FAILURE(s) ? -EIO : 0;
}

static int mi_stage_c(struct mi_tm *m, u8 dt2a, u8 r, u8 g, u8 b)
{
	u8 buf[WSAA_BUFLEN] = { 0 };

	buf[0] = 0x00; buf[1] = 0xfb;	/* DAT0 = 0xFB00 (write) */
	buf[2] = 0x01; buf[3] = 0x01;	/* DAT1 = 0x0101 SetColour */
	buf[4] = dt2a;			/* DT2A: which C-reg */
	buf[5] = 0x02;			/* DT2B (LCAM commit) */
	buf[8]  = r;			/* DT3A */
	buf[9]  = g;			/* DT3B */
	buf[10] = b;			/* DT3C */
	return mi_wsaa(m, buf);
}

static int mi_lighteffect(struct mi_tm *m, u8 ledz, u8 lety, u8 lspd, u8 lebr)
{
	u8 buf[WSAA_BUFLEN] = { 0 };

	buf[0] = 0x00; buf[1] = 0xfb;	/* DAT0 = 0xFB00 */
	buf[2] = 0x00; buf[3] = 0x01;	/* DAT1 = 0x0100 SetLightEffect */
	buf[4] = ledz;			/* GWF2 -> LEDZ */
	buf[8]  = lety;			/* DT3A -> LETY */
	buf[9]  = lspd;			/* DT3B -> LSPD */
	buf[10] = lebr;			/* DT3C -> LEBR (= current KBBR) */
	return mi_wsaa(m, buf);
}

/*
 * Paint one zone.  Caller must hold m->lock.
 * r/g/b are the final brightness-scaled values (0-255).
 */
static int mi_paint_zone(struct mi_tm *m, u8 ledz, u8 r, u8 g, u8 b, u8 kbbr)
{
	int ret;

	ret = mi_stage_c(m, DT2A_C0Z, r, g, b);
	if (ret)
		return ret;

	ret = mi_lighteffect(m, ledz, LETY_STATIC, m->speed, kbbr);
	if (ret)
		return ret;

	if (m->effect != LETY_STATIC)
		ret = mi_lighteffect(m, ledz, m->effect, m->speed, kbbr);

	return ret;
}

/* Compute brightness-scaled colour from the LED classdev state. */
static void mi_zone_rgb(struct mi_zone *z, u8 *r, u8 *g, u8 *b)
{
	struct led_classdev *led = &z->mc.led_cdev;
	int bright = led->brightness;
	int max = led->max_brightness;
	if (!max) max = 255;
	*r = z->mc.subled_info[0].intensity * bright / max;
	*g = z->mc.subled_info[1].intensity * bright / max;
	*b = z->mc.subled_info[2].intensity * bright / max;
}

/*
 * mi_commit() – batch-paint all zones in one shot.
 *
 * Reads the brightness-scaled RGB directly from each zone's LED classdev
 * state (subled_info[].intensity * brightness / max_brightness).  This
 * works regardless of whether mi_brightness_set was called (the LED
 * framework always stores intensities and brightness on write).
 *
 * If all zones share the same colour, stages C0Z once (and C1Z once for
 * COLORFUL), then fires LightEffect on all 4 zones.  If colours differ,
 * paints each zone individually but shares the single KBBR read and the
 * single C1Z stage.
 *
 * Caller must hold m->lock.
 */
static int mi_commit(struct mi_tm *m)
{
	u8 kbbr, zr[NUM_ZONES], zg[NUM_ZONES], zb[NUM_ZONES];
	int ret, i;
	bool uniform = true;

	ret = mi_read_kbbr(&kbbr);
	if (ret)
		return ret;
	if (kbbr == 5)
		return -ENXIO;

	/* Read each zone's colour from LED classdev state. */
	for (i = 0; i < NUM_ZONES; i++)
		mi_zone_rgb(&m->zones[i], &zr[i], &zg[i], &zb[i]);

	/* Check if all zones have the same colour. */
	for (i = 1; i < NUM_ZONES; i++) {
		if (zr[i] != zr[0] || zg[i] != zg[0] || zb[i] != zb[0]) {
			uniform = false;
			break;
		}
	}

	if (m->effect == LETY_COLORFUL) {
		ret = mi_stage_c(m, DT2A_C1Z, m->sec_r, m->sec_g, m->sec_b);
		if (ret)
			return ret;
	}

	if (uniform) {
		/* Stage C0Z once, then fire all 4 zones. */
		ret = mi_stage_c(m, DT2A_C0Z, zr[0], zg[0], zb[0]);
		if (ret)
			return ret;
		for (i = 0; i < NUM_ZONES; i++) {
			ret = mi_lighteffect(m, m->zones[i].ledz,
					     LETY_STATIC, m->speed, kbbr);
			if (ret)
				return ret;
		}
		if (m->effect != LETY_STATIC) {
			for (i = 0; i < NUM_ZONES; i++) {
				ret = mi_lighteffect(m, m->zones[i].ledz,
						     m->effect, m->speed, kbbr);
				if (ret)
					return ret;
			}
		}
	} else {
		/* Different colours per zone – paint one at a time. */
		for (i = 0; i < NUM_ZONES; i++) {
			ret = mi_paint_zone(m, m->zones[i].ledz,
					    zr[i], zg[i], zb[i], kbbr);
			if (ret)
				return ret;
		}
	}

	return 0;
}

/*
 * Brightness-set callback – a no-op.
 *
 * The LED framework calls this for `brightness` writes but NOT for
 * `multi_intensity` writes (the framework sets led_cdev->brightness
 * before calling led_set_brightness, which matches the early-return
 * check and skips our callback).
 *
 * Instead of relying on this callback to cache colours, mi_commit()
 * reads the brightness-scaled RGB directly from the LED classdev state
 * (subled_info[i].intensity * brightness / max_brightness).
 *
 * We still call led_mc_calc_color_components() here so the subled
 * brightness values are coherent if anything reads them.
 */
static int mi_brightness_set(struct led_classdev *led_cdev,
			     enum led_brightness brightness)
{
	struct led_classdev_mc *mc = lcdev_to_mccdev(led_cdev);

	led_mc_calc_color_components(mc, brightness);
	return 0;
}

static ssize_t effect_show(struct device *dev, struct device_attribute *attr,
			    char *buf)
{
	struct mi_tm *m = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%u\n", m->effect);
}

static ssize_t effect_store(struct device *dev, struct device_attribute *attr,
			     const char *buf, size_t count)
{
	struct mi_tm *m = dev_get_drvdata(dev);
	u8 val;
	int ret;

	ret = kstrtou8(buf, 0, &val);
	if (ret)
		return ret;
	if (val < LETY_STATIC || val > LETY_COLORFUL)
		return -EINVAL;

	mutex_lock(&m->lock);
	m->effect = val;
	mutex_unlock(&m->lock);
	return count;
}
static DEVICE_ATTR_RW(effect);

static ssize_t speed_show(struct device *dev, struct device_attribute *attr,
			   char *buf)
{
	struct mi_tm *m = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%u\n", m->speed);
}

static ssize_t speed_store(struct device *dev, struct device_attribute *attr,
			    const char *buf, size_t count)
{
	struct mi_tm *m = dev_get_drvdata(dev);
	u8 val;
	int ret;

	ret = kstrtou8(buf, 0, &val);
	if (ret)
		return ret;
	if (val > 2)
		return -EINVAL;

	mutex_lock(&m->lock);
	m->speed = val;
	mutex_unlock(&m->lock);
	return count;
}
static DEVICE_ATTR_RW(speed);

static ssize_t secondary_color_show(struct device *dev,
				     struct device_attribute *attr, char *buf)
{
	struct mi_tm *m = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%02x%02x%02x\n",
			  m->sec_r, m->sec_g, m->sec_b);
}

static ssize_t secondary_color_store(struct device *dev,
				      struct device_attribute *attr,
				      const char *buf, size_t count)
{
	struct mi_tm *m = dev_get_drvdata(dev);
	const char *p = buf;
	unsigned int r, g, b;

	while (*p == ' ' || *p == '\t')
		p++;
	if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X'))
		p += 2;
	else if (p[0] == '#')
		p++;
	if (sscanf(p, "%2x%2x%2x", &r, &g, &b) != 3 ||
	    r > 0xff || g > 0xff || b > 0xff)
		return -EINVAL;

	mutex_lock(&m->lock);
	m->sec_r = r; m->sec_g = g; m->sec_b = b;
	mutex_unlock(&m->lock);
	return count;
}
static DEVICE_ATTR_RW(secondary_color);

static ssize_t panel_brightness_show(struct device *dev,
				      struct device_attribute *attr, char *buf)
{
	u8 kbbr;
	int ret;

	ret = mi_read_kbbr(&kbbr);
	if (ret)
		return ret;
	return sysfs_emit(buf, "%u\n", kbbr);
}

static ssize_t panel_brightness_store(struct device *dev,
				       struct device_attribute *attr,
				       const char *buf, size_t count)
{
	struct mi_tm *m = dev_get_drvdata(dev);
	u8 val;
	int ret;

	ret = kstrtou8(buf, 0, &val);
	if (ret)
		return ret;
	if (val > 5)
		return -EINVAL;

	/* FB00/0100 LightEffect on LEDZ=01 (logo slot, no LED on this
	 * hardware) writes LEBR; the EC mirrors LEBR into KBBR. */
	mutex_lock(&m->lock);
	ret = mi_lighteffect(m, 0x01, LETY_STATIC, m->speed, val);
	mutex_unlock(&m->lock);
	return ret ? ret : count;
}
static DEVICE_ATTR_RW(panel_brightness);

/*
 * commit – batch-paint all zones from their stored colors.
 * Write any positive integer to trigger an atomic commit.
 *
 * Without this, multi_intensity / brightness writes only store
 * values; nothing hits the EC until commit is written.
 */
static ssize_t commit_store(struct device *dev,
			     struct device_attribute *attr,
			     const char *buf, size_t count)
{
	struct mi_tm *m = dev_get_drvdata(dev);
	unsigned int val;
	int ret;

	ret = kstrtouint(buf, 0, &val);
	if (ret)
		return ret;
	if (val == 0)
		return -EINVAL;

	mutex_lock(&m->lock);
	ret = mi_commit(m);
	mutex_unlock(&m->lock);
	return ret ? ret : count;
}
static DEVICE_ATTR_WO(commit);

static struct attribute *mi_attrs[] = {
	&dev_attr_effect.attr,
	&dev_attr_speed.attr,
	&dev_attr_secondary_color.attr,
	&dev_attr_panel_brightness.attr,
	&dev_attr_commit.attr,
	NULL,
};
ATTRIBUTE_GROUPS(mi);

static int mi_zone_init(struct mi_tm *m, int idx)
{
	struct mi_zone *z = &m->zones[idx];
	struct led_classdev *led;
	char *name;

	z->ledz = mi_zone_defs[idx].ledz;
	z->name = mi_zone_defs[idx].name;

	z->subleds[0].color_index = LED_COLOR_ID_RED;
	z->subleds[1].color_index = LED_COLOR_ID_GREEN;
	z->subleds[2].color_index = LED_COLOR_ID_BLUE;

	z->mc.subled_info = z->subleds;
	z->mc.num_colors = 3;

	led = &z->mc.led_cdev;
	name = devm_kasprintf(&m->wdev->dev, GFP_KERNEL,
			      "mi_tm1806::kbd_%s", z->name);
	if (!name)
		return -ENOMEM;

	led->name = name;
	led->max_brightness = 255;
	led->brightness = 255;  /* default: max, so first multi_intensity write updates brightness */
	led->brightness_set_blocking = mi_brightness_set;

	return devm_led_classdev_multicolor_register(&m->wdev->dev, &z->mc);
}

static int mi_probe(struct wmi_device *wdev, const void *context)
{
	struct mi_tm *m;
	int i, ret;
	u8 kbbr;

	m = devm_kzalloc(&wdev->dev, sizeof(*m), GFP_KERNEL);
	if (!m)
		return -ENOMEM;

	m->wdev = wdev;
	mutex_init(&m->lock);
	m->effect = LETY_STATIC;
	m->speed = 2;
	dev_set_drvdata(&wdev->dev, m);

	for (i = 0; i < NUM_ZONES; i++) {
		ret = mi_zone_init(m, i);
		if (ret) {
			dev_err(&wdev->dev,
				"failed to register zone %s: %d\n",
				mi_zone_defs[i].name, ret);
			return ret;
		}
	}

	if (mi_read_kbbr(&kbbr) == 0)
		dev_info(&wdev->dev,
			 "ready: 4 zones registered, KBBR=%u%s\n", kbbr,
			 kbbr == 5 ?
			 " (panel off; press Fn+brightness once to wake)" :
			 "");
	else
		dev_info(&wdev->dev,
			 "ready: 4 zones registered (KBBR read failed)\n");

	return 0;
}

static const struct wmi_device_id mi_wmi_id_table[] = {
	{ .guid_string = WSAA_GUID },
	{ }
};
MODULE_DEVICE_TABLE(wmi, mi_wmi_id_table);

static struct wmi_driver mi_wmi_driver = {
	.driver = {
		.name = "mi-tm1806-led",
		.dev_groups = mi_groups,
	},
	.id_table = mi_wmi_id_table,
	.probe = mi_probe,
};
module_wmi_driver(mi_wmi_driver);

MODULE_DESCRIPTION("Xiaomi Mi Gaming Laptop (TIMI TM1806) RGB keyboard backlight");
MODULE_LICENSE("Dual MIT/GPL");
