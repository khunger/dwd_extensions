'''
Created on 05.01.2015

@author: Christian Kliche <chk@ebp.de>
'''
import copy
import numpy as np
import numpy.ma
import logging

from types import *

import mpop.imageo.geo_image as geo_image

from mpop.channel import Channel
from mpop.satellites import GeostationaryFactory

try:
    from pyorbital.astronomy import sun_zenith_angle as sza
except ImportError:
    sza = None


LOGGER = logging.getLogger(__name__)
# conversion factor K<->C
CONVERSION = 273.15
    
def _dwd_create_single_channel_image(self, chn):
    """Creates a calibrated and corrected single channel black/white image.
    Data calibration:
    HRV, VIS channels: albedo 0 - 125 %
    IR channels: temperature -87.5 - +40 C
    Data correction:
    HRV, VIS channels: sun zenith angle correction
    IR channels: 
    """
    if not isinstance(chn, basestring):
        return None
    
    self.check_channels(chn)
    
    # apply calibrations and corrections on channels
    if not self._dwd_channel_preparation(chn):
        return None
    
    if self._is_solar_channel(chn):
        img = geo_image.GeoImage(self[chn].data,
                                 self.area,
                                 self.time_slot,
                                 fill_value=0,
                                 mode="L",
                                 crange=(0, 125))
    else:
        img = geo_image.GeoImage(self[chn].data,
                                 self.area,
                                 self.time_slot,
                                 fill_value=0,
                                 mode="L",
                                 crange=(-87.5, 40))
        img.enhance(inverse=True)
        
    return img

def _dwd_apply_sun_zenith_angle_correction(self, chn):
    """Apply sun zenith angle correction on solar channel data.
    """
    if self._is_solar_channel(chn) and \
    self[chn].info.get("sun_zen_corrected", None) is None:
        self[chn].data = self[chn].sunzen_corr(self.time_slot, limit=85.).data

def _dwd_kelvin_to_celsius(self, chn):
    """Apply Kelvin to Celsius conversion on infrared channels.
    """
    if not self._is_solar_channel(chn) and \
        (self[chn].info['units'] == 'K' or self[chn].unit == 'K'):
            self[chn].data -= CONVERSION
            self[chn].info['units'] = self[chn].unit = 'C'

def _is_solar_channel(self, chn):
    """Checks whether the wave length of the given channel corresponds to solar wave length.
    Returns true if the given channel is a visual one; false otherwise.
    """
    return self[chn].wavelength_range[2] < 4 or chn in ['HRV', 'VIS006', 'VIS008', 'IR_016']

def _dwd_channel_preparation(self, *chn):
    """Applies to the given channels DWD specific calibrations and corrections.
    Returns True if the calculations were successful; False otherwise.
    """
    result = True
    
    for c in chn:
        self._dwd_apply_sun_zenith_angle_correction(c)
        self._dwd_kelvin_to_celsius(c)
        if self[c].info['units'] != 'C' and self[c].info['units'] != '%':
            result = False
            LOGGER.error("Calibration for channel " + str(c) +
                         " failed due to unknown unit " + self[c].info['units'])
    return result

def _dwd_calculate_sun_zenith_angles(self):
    LOGGER.info('Retrieve sun zenith angles')
    try:
        data = getattr(self, "_data_holder")
    except AttributeError:
        LOGGER.error("No such data: _data_holder")
        return False

    try:
        data.__getattribute__("sun_zen")
    except AttributeError:
        if data.area.lons is None:
            LOGGER.debug("Load coordinates for _data_holder")
            data.area.lons, data.area.lats = data.area.get_lonlats()

        LOGGER.debug("Calculating Sun zenith angles for _data_holder")
        data.sun_zen = np.zeros(shape=data.area.lons.shape)
        q = 500
        for start in xrange(0, data.sun_zen.shape[1], q):
            data.sun_zen[:,start:start+q] = sza(data.time_slot, 
                                                data.area.lons[:,start:start+q], 
                                                data.area.lats[:,start:start+q])
    
        #data.sun_zen = sza(data.time_slot, data.area.lons, data.area.lats)
    return True

def _dwd_get_day_mask(self):
    if self._dwd_calculate_sun_zenith_angles():
        data = getattr(self, "_data_holder").__getattribute__("sun_zen")
        return np.ma.getmaskarray(np.ma.masked_outside(data, 0.0, 85.0))
    else:
        return None

def _dwd_get_night_mask(self):
    if self._dwd_calculate_sun_zenith_angles():
        data = getattr(self, "_data_holder").__getattribute__("sun_zen")
        return np.ma.getmaskarray(np.ma.masked_inside(data, 0.0, 87.0))
    else:
        return None

def _dwd_get_hrvc(self):
    try:
        self.check_channels("HRVC")
        if self["HRVC"].area != self.area:
            self._data_holder.channels.remove(self["HRVC"])
            raise Exception()
    except:
        hrvc_chn = copy.deepcopy(self["HRV"])
        hrvc_chn.name = "HRVC"
        hrvc_chn.data = np.ma.where(self["HRV"].data.mask, self[0.85].data, self["HRV"].data)
        self._data_holder.channels.append(hrvc_chn)
    
    return hrvc_chn

def _dwd_get_scaled_data(self, data, color_min, color_max, inverse=False):
    """Scales the given data to the specified color range.
    """
    if color_min == color_max:
        raise Exception("Scaling of data failed due to " + color_min +
                        " == " + color_max)
    
    if color_min > color_max:
        temp = color_min
        color_min = color_max
        color_max = temp
        
    if isinstance(data, np.ma.core.MaskedArray):
        data_data = data.data
        data_mask = data.mask
    else:
        data_data = np.array(data)
        data_mask = False
        
    if inverse:
        scaled = (1.0 - ((data_data - color_min) *
                  1.0 / (color_max - color_min)))
    else:
        scaled = ((data_data - color_min) *
                  1.0 / (color_max - color_min))
    
    return np.ma.array(scaled, mask=data_mask)



def dwd_airmass(self):
    """Make a DWD specific RGB image composite.
    +--------------------+--------------------+--------------------+
    | Channels           | Span               | Gamma              |
    +====================+====================+====================+
    | WV6.2 - WV7.3      |     -25 to 0 K     | gamma 1            |
    +--------------------+--------------------+--------------------+
    | IR9.7 - IR10.8     |     -40 to 5 K     | gamma 1            |
    +--------------------+--------------------+--------------------+
    | WV6.2              |     243 to 208 K   | gamma 1            |
    +--------------------+--------------------+--------------------+
    """
    self.check_channels(6.7, 7.3, 9.7, 10.8)
    
    if not self._dwd_channel_preparation(6.7, 7.3, 9.7, 10.8):
        return None

    ch1 = self[6.7].data - self[7.3].data
    ch2 = self[9.7].data - self[10.8].data
    ch3 = self[6.7].data

    img = geo_image.GeoImage((ch1, ch2, ch3),
                             self.area,
                             self.time_slot,
                             fill_value=(0, 0, 0),
                             mode="RGB",
                             crange=((-25 - CONVERSION, 0 - CONVERSION),
                                     (-40 - CONVERSION, 5 - CONVERSION),
                                     (243 - CONVERSION, 208 - CONVERSION)))
    return img

dwd_airmass.prerequisites = set([6.7, 7.3, 9.7, 10.8])

def dwd_schwere_konvektion_tag(self):
    """Make a DWD specific RGB image composite.
    +--------------------+--------------------+--------------------+
    | Channels           | Span               | Gamma              |
    +====================+====================+====================+
    | WV6.2 - WV7.3      |     -35 to 5 K     | gamma 1            |
    +--------------------+--------------------+--------------------+
    | IR3.9 - IR10.8     |      -5 to 60 K    | gamma 0.5          |
    +--------------------+--------------------+--------------------+
    | IR1.6 - VIS0.6     |     -75 to 25 %    | gamma 1            |
    +--------------------+--------------------+--------------------+
    """
    self.check_channels(0.635, 1.63, 3.75, 6.7, 7.3, 10.8)
    
    if not self._dwd_channel_preparation(0.635, 1.63, 3.75, 6.7, 7.3, 10.8):
        return None
            
    ch1 = self[6.7].data - self[7.3].data
    ch2 = self[3.75].data - self[10.8].data
    ch3 = self[1.63].check_range() - self[0.635].check_range()

    img = geo_image.GeoImage((ch1, ch2, ch3),
                             self.area,
                             self.time_slot,
                             fill_value=(0, 0, 0),
                             mode="RGB",
                             crange=((-35 - CONVERSION, 5 - CONVERSION),
                                     (-5 - CONVERSION, 60 - CONVERSION),
                                     (-75, 25)))
    img.enhance(gamma=(1.0, 0.5, 1.0))

    return img

dwd_schwere_konvektion_tag.prerequisites = set([0.635, 1.63, 3.75, 6.7, 7.3, 10.8])

def dwd_dust(self):
    """Make a DWD specific RGB image composite.

    +--------------------+--------------------+--------------------+
    | Channels           | Span               | Gamma              |
    +====================+====================+====================+
    | IR12.0 - IR10.8    |     -4 to 2 K      | gamma 1            |
    +--------------------+--------------------+--------------------+
    | IR10.8 - IR8.7     |     0 to 15 K      | gamma 2.5          |
    +--------------------+--------------------+--------------------+
    | IR10.8             |   261 to 289 K     | gamma 1            |
    +--------------------+--------------------+--------------------+
    """
    self.check_channels(8.7, 10.8, 12.0)
    
    if not self._dwd_channel_preparation(8.7, 10.8, 12.0):
        return None

    ch1 = self[12.0].data - self[10.8].data
    ch2 = self[10.8].data - self[8.7].data
    ch3 = self[10.8].data
    img = geo_image.GeoImage((ch1, ch2, ch3),
                             self.area,
                             self.time_slot,
                             fill_value=(0, 0, 0),
                             mode="RGB",
                             crange=((-4 - CONVERSION, 2 - CONVERSION),
                                     (0 - CONVERSION, 15 - CONVERSION),
                                     (261 - CONVERSION, 289 - CONVERSION)))
    img.enhance(gamma=(1.0, 2.5, 1.0))

    return img

dwd_dust.prerequisites = set([8.7, 10.8, 12.0])   

def dwd_RGB_12_12_1_N(self):
    """Make a DWD specific composite depending sun zenith angle.
    +--------------------+--------------------+--------------------+
    | Channels           | Span               | Gamma              |
    +====================+====================+====================+
    | HRV                |   0.0 to 100.0 %   |        1.3         |
    +--------------------+--------------------+--------------------+
    | HRV                |   0.0 to 100.0 %   |        1.3         |
    +--------------------+--------------------+--------------------+
    | VIS006             |   0.0 to 100.0 %   |        1.3         |
    +--------------------+--------------------+--------------------+ 
    Use IR10.8 for the night.
    """
    self.check_channels(0.635, "HRV", 10.8)
    
    if not self._dwd_channel_preparation(0.635, "HRV", 10.8):
        return None
    
    # scale each channel to the required color range
    try:
        hrv_data = self._dwd_get_scaled_data(self["HRV"].data, 0, 100)
        vis006_data = self._dwd_get_scaled_data(self[0.635].data, 0, 100)
        ir108_data_inv = self._dwd_get_scaled_data(self[10.8].data, -87.5, 40, inverse=True)
    except Exception as ex:
        LOGGER.error(str(ex))
        return None
    
    day_mask = self._dwd_get_day_mask()
    if day_mask is None:
        LOGGER.error("creating day mask failed")
        return None
    
    ch1 = np.ma.where(day_mask, ir108_data_inv, hrv_data)
    ch2 = np.ma.where(day_mask, ir108_data_inv, vis006_data)
    
    img = geo_image.GeoImage((ch1, ch1, ch2),
                             self.area,
                             self.time_slot,
                             fill_value=(0, 0, 0),
                             mode="RGB")
    img.enhance(gamma=(1.3, 1.3, 1.3))

    return img

dwd_RGB_12_12_1_N.prerequisites = set([0.635, "HRV", 10.8])

def dwd_RGB_12_12_9i_N(self):
    """Make a DWD specific composite depending sun zenith angle.
    day:
    +--------------------+--------------------+--------------------+
    | Channels           | Span               | Gamma              |
    +====================+====================+====================+
    | HRVC               |   0.0 to 100.0 %   |        1.0         |
    +--------------------+--------------------+--------------------+
    | HRVC               |   0.0 to 100.0 %   |        1.0         |
    +--------------------+--------------------+--------------------+
    | IR108              |  323.0 to 203.0 K  |        1.0         |
    +--------------------+--------------------+--------------------+ 
    night:
    +--------------------+--------------------+--------------------+
    | Channels           | Span               | Gamma              |
    +====================+====================+====================+
    | IR039 (inverted)   |         ---        |        1.0         |
    +--------------------+--------------------+--------------------+
    | IR108 (inverted)   |         ---        |        1.0         |
    +--------------------+--------------------+--------------------+
    | IR120 (inverted)   |         ---        |        1.0         |
    +--------------------+--------------------+--------------------+ 
    """
    self.check_channels("HRV", 0.85, 10.8, 3.75, 12.0)
    
    if not self._dwd_channel_preparation("HRV", 0.85, 10.8, 3.75, 12.0):
        return None
    
    day_mask = self._dwd_get_day_mask()
    if day_mask is None:
        return None
     
    hrvc_chn = self._dwd_get_hrvc()
    
    # scale each channel to the required color range
    try:
        hrvc_data = self._dwd_get_scaled_data(hrvc_chn.data, 0, 100)
        ir108_data = self._dwd_get_scaled_data(self[10.8].data, 203 - CONVERSION, 323 - CONVERSION)
        night_data1_inv = self._dwd_get_scaled_data(self[3.75].data, -87.5, 40, inverse=True)
        night_data2_inv = self._dwd_get_scaled_data(self[10.8].data, -87.5, 40, inverse=True)
        night_data3_inv = self._dwd_get_scaled_data(self[12.0].data, -87.5, 40, inverse=True)
    except Exception as ex:
        LOGGER.error(str(ex))
        return None       
    
    # create a temporary image to apply histogram equalisation on each channel
    tmp_img = geo_image.GeoImage((night_data1_inv, night_data2_inv, night_data3_inv),
                                 self.area,
                                 self.time_slot,
                                 fill_value=(0, 0, 0),
                                 mode="RGB")
    tmp_img.enhance(stretch = "histogram")
    
    # apply the mask on the input data
    ch_data1 = np.ma.where(day_mask, tmp_img.channels[0].data, hrvc_data)
    ch_data2 = np.ma.where(day_mask, tmp_img.channels[1].data, hrvc_data)
    ch_data3 = np.ma.where(day_mask, tmp_img.channels[2].data, ir108_data)
    
    # create the image
    img = geo_image.GeoImage((ch_data1, ch_data2, ch_data3),
                             self.area,
                             self.time_slot,
                             fill_value=(0, 0, 0),
                             mode="RGB")
    
    return img
    
dwd_RGB_12_12_9i_N.prerequisites = set(["HRV", 0.85, 10.8, 3.75, 12.0])
    
def dwd_ninjo_VIS006(self):
    return self._dwd_create_single_channel_image('VIS006')

dwd_ninjo_VIS006.prerequisites = set(['VIS006'])

def dwd_ninjo_VIS008(self):
    return self._dwd_create_single_channel_image('VIS008')

dwd_ninjo_VIS008.prerequisites = set(['VIS008'])

def dwd_ninjo_IR_016(self):
    return self._dwd_create_single_channel_image('IR_016')

dwd_ninjo_IR_016.prerequisites = set(['IR_016'])

def dwd_ninjo_IR_039(self):
    return self._dwd_create_single_channel_image('IR_039')

dwd_ninjo_IR_039.prerequisites = set(['IR_039'])

def dwd_ninjo_WV_062(self):
    return self._dwd_create_single_channel_image('WV_062')

dwd_ninjo_WV_062.prerequisites = set(['WV_062'])

def dwd_ninjo_WV_073(self):
    return self._dwd_create_single_channel_image('WV_073')

dwd_ninjo_WV_073.prerequisites = set(['WV_073'])

def dwd_ninjo_IR_087(self):
    return self._dwd_create_single_channel_image('IR_087')

dwd_ninjo_IR_087.prerequisites = set(['IR_087'])

def dwd_ninjo_IR_097(self):
    return self._dwd_create_single_channel_image('IR_097')

dwd_ninjo_IR_097.prerequisites = set(['IR_097'])

def dwd_ninjo_IR_108(self):
    return self._dwd_create_single_channel_image('IR_108')

dwd_ninjo_IR_108.prerequisites = set(['IR_108'])

def dwd_ninjo_IR_120(self):
    return self._dwd_create_single_channel_image('IR_120')

dwd_ninjo_IR_120.prerequisites = set(['IR_120'])

def dwd_ninjo_IR_134(self):
    return self._dwd_create_single_channel_image('IR_134')

dwd_ninjo_IR_134.prerequisites = set(['IR_134'])
        
def dwd_ninjo_HRV(self):
    return self._dwd_create_single_channel_image('HRV')

dwd_ninjo_HRV.prerequisites = set(['HRV'])
   
seviri = [_is_solar_channel, _dwd_kelvin_to_celsius, _dwd_apply_sun_zenith_angle_correction,
          _dwd_channel_preparation, _dwd_create_single_channel_image,
          _dwd_calculate_sun_zenith_angles, _dwd_get_day_mask, _dwd_get_night_mask,
          _dwd_get_hrvc, _dwd_get_scaled_data,
          dwd_ninjo_VIS006, dwd_ninjo_VIS008, dwd_ninjo_IR_016, dwd_ninjo_IR_039,
          dwd_ninjo_WV_062, dwd_ninjo_WV_073, dwd_ninjo_IR_087, dwd_ninjo_IR_097,
          dwd_ninjo_IR_108, dwd_ninjo_IR_120, dwd_ninjo_IR_134, dwd_ninjo_HRV,
          dwd_airmass, dwd_schwere_konvektion_tag, dwd_dust, dwd_RGB_12_12_1_N,
          dwd_RGB_12_12_9i_N]
