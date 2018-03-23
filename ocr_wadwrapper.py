#!/usr/bin/env python
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# PyWAD is open-source software and consists of a set of modules written in python for the WAD-Software medical physics quality control software. 
# The WAD Software can be found on https://github.com/wadqc
# 
# The pywad package includes modules for the automated analysis of QC images for various imaging modalities. 
# PyWAD has been originaly initiated by Dennis Dickerscheid (AZN), Arnold Schilham (UMCU), Rob van Rooij (UMCU) and Tim de Wit (AMC) 
#
#
# Changelog:
#   20171117: sync with US module; removed data reading by wadwrapper_lib
#   20161220: removed class variables; removed testing stuff
#   20160901: first version, combination of TdW, JG, AS
#
# mkdir -p TestSet/StudyCurve
# mkdir -p TestSet/Config
# cp ~/Downloads/1/us_philips_*.xml TestSet/Config/
# ln -s /home/nol/WAD/pyWADdemodata/US/US_AirReverberations/dicom_curve/ TestSet/StudyCurve/
# ./ocr_wadwrapper.py -d TestSet/StudyEpiqCurve/ -c Config/ocr_philips_epiq.json -r results_epiq.json
#
from __future__ import print_function

__version__ = '20171117'
__author__ = 'aschilham'

import os
# this will fail unless wad_qc is already installed
from wad_qc.module import pyWADinput
from wad_qc.modulelibs import wadwrapper_lib
try:
    import pydicom as dicom
except ImportError:
    import dicom

import numpy as np
import ocr_lib

def logTag():
    return "[OCR_wadwrapper] "

def readdcm(inputfile, channel, slicenr):
    """
    Use pydicom to read the image. Only implement 2D reading, and do not transpose axes.
      channel: either a number in [0, number of channels] or 'sum':
          use the given channel only or sum all channels to get a gray scale image.
      slicenr: use the given slicenr if the dicom file contains a 3D image
    """
    dcmInfile = dicom.read_file(inputfile)
    pixeldataIn = dcmInfile.pixel_array

    # check if this is multi-channel (RGB) data. If so, use the user defined method to convert it to gray scale
    channels = dcmInfile.get('SamplesPerPixel', 1)

    # first check single channel data
    if channels == 1: #
        # if this is 3D data in a single image, use only the defined slice
        if len(np.shape(pixeldataIn)) == 3:
            pixeldataIn = pixeldataIn[slicenr]

        return dcmInfile, pixeldataIn

    ## multi-channel data
    # this fix is needed in pydicom < 1.0; maybe solved in later versions?
    try:
        nofframes = dcmInfile.NumberOfFrames
    except AttributeError:
        nofframes = 1
    if dcmInfile.PlanarConfiguration==0:
        pixel_array = pixeldataIn.reshape(nofframes, dcmInfile.Rows, dcmInfile.Columns, dcmInfile.SamplesPerPixel)
    else:
        pixel_array = pixeldataIn.reshape(dcmInfile.SamplesPerPixel, nofframes, dcmInfile.Rows, dcmInfile.Columns)

    # first simple cases
    if isinstance(channel, int):
        if(channel>=channels or channel<0):
            raise ValueError("Data has {} channels. Invalid selected channel {}! Should be a number or 'sum'.".format(channels, channel))

        if len(np.shape(pixel_array)) == 4: #3d multi channel
            if dcmInfile.PlanarConfiguration==0:
                pixeldataIn = pixel_array[slicenr, :, :, channel]
            else:
                pixeldataIn = pixel_array[channel, slicenr, :, :]# e.g. ALOKA images
        else:
            pixeldataIn = pixeldataIn[:, :, channel]
            
        return dcmInfile, pixeldataIn
        
    # special values for channel:
    if channel == 'sum':
        # add all channels
        if len(np.shape(pixel_array)) == 4: #3d multi channel
            pixeldataIn = pixel_array[slicenr, :, :, 0]
            for c in range(1, channels):
                pixeldataIn += pixel_array[slicenr, :, :, c]
        else:
            pixeldataIn = pixel_array[:, :, 0]
            for c in range(1, channels):
                pixeldataIn += pixel_array[:, :, c]

        return dcmInfile, pixeldataIn/channels # ocr_lib expects pixel values 0-255

    raise ValueError("Data has {} channels. Invalid selected channel {}! Should be a number or 'sum'.".format(channels, channel))
    
    
def OCR(data, results, action):
    """
    Use pyOCR which for OCR
    """
    try:
        params = action['params']
    except KeyError:
        params = {}

    channel = params.get('channel', 'sum')
    slicenr = params.get('slicenr', -1)
    ocr_threshold = params.get('ocr_threshold', 0)
    ocr_zoom = params.get('ocr_zoom', 10)

    inputfile = data.series_filelist[0][0] # only single images 
    dcmInfile, pixeldataIn = readdcm(inputfile, channel, slicenr)

    # solve ocr params
    regions = {}
    for k,v in params.items():
        #'OCR_TissueIndex:xywh' = 'x;y;w;h'
        #'OCR_TissueIndex:prefix' = 'prefix'
        #'OCR_TissueIndex:suffix' = 'suffix'
        if k.startswith('OCR_'):
            split = k.find(':')
            name = k[:split]
            stuff = k[split+1:]
            if not name in regions:
                regions[name] = {'prefix':'', 'suffix':''}
            if stuff == 'xywh':
                regions[name]['xywh'] = [int(p) for p in v.split(';')]
            elif stuff == 'prefix':
                regions[name]['prefix'] = v
            elif stuff == 'suffix':
                regions[name]['suffix'] = v
            elif stuff == 'type':
                regions[name]['type'] = v

    for name, region in regions.items():
        txt, part = ocr_lib.OCR(pixeldataIn, region['xywh'], ocr_zoom=ocr_zoom, ocr_threshold=ocr_threshold, transposed=False)
        if region['type'] == 'object':
            import scipy
            im = scipy.misc.toimage(part) 
            fn = '%s.jpg'%name
            im.save(fn)
            results.addObject(name, fn)
            
        else:
            value = ocr_lib.txt2type(txt, region['type'], region['prefix'],region['suffix'])
            if region['type'] == 'float':
                results.addFloat(name, value)
            elif region['type'] == 'string':
                results.addString(name, value)
            elif region['type'] == 'bool':
                results.addBool(name, value)

def acqdatetime_series(data, results, action):
    """
    Read acqdatetime from dicomheaders and write to IQC database

    Workflow:
        1. Read only headers
    """
    try:
        params = action['params']
    except KeyError:
        params = {}

    ## 1. read only headers
    dcmInfile = dicom.read_file(data.series_filelist[0][0], stop_before_pixels=True)

    dt = wadwrapper_lib.acqdatetime_series(dcmInfile)

    results.addDateTime('AcquisitionDateTime', dt) 

if __name__ == "__main__":
    data, results, config = pyWADinput()

    # read runtime parameters for module
    for name,action in config['actions'].items():
        if name == 'acqdatetime':
            acqdatetime_series(data, results, action)
        elif name == 'qc_series':
            OCR(data, results, action)

    #results.limits["minlowhighmax"]["mydynamicresult"] = [1,2,3,4]

    results.write()
