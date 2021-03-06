''' 
ExtractRasterValuesToPoints.py

Created by: 
Dori Dick
College of Earth, Ocean, and Atmospheric Sciences
Oregon State Univeristy
 
Created on: 3 March 2012
Last modified: 12 May 2013
 
Description: 
This script extracts raster values from one or more raster layers based on 
an input point feature class.  The extracted values are added to the input 
feature class via a new attribute field.  Each new attribute field is named 
after the respective raster layer.

Raster values are based on the cell center, no interpolation of nearby cell occurs.

Caution: 
This script modifies the input data

Required Inputs:
One or more raster layers

Script Outputs: 
The addition of one or more new attribute fields containing extracted values from 
the raster layer(s) to the input feature class.
 
NOTE:
This script requires the input feature layer to be selected on the geneGIS toolbar.

This script was developed and tested on ArcGIS 10.1 and Python 2.7.
'''
import os
import sys

import arcpy
from arcpy.sa import ExtractMultiValuesToPoints

# local imports
import utils
import config
settings = config.settings()

def main(input_raster=None, selected_layer=None, interpolate=None, 
         mode=settings.mode):

        utils.msg("Executing ExtractRasterValuesToPoints.")   
        arcpy.CheckOutExtension("Spatial")

        # was bilinear interpolation asked for? maps to
        # 'bilinear_intepolate_values'.
        if interpolate in ('BILINEAR', True):
            bilinear = 'BILINEAR'
        else:
            bilinear = 'NONE'

        # create a value table, prefix all output rasters with 'R_'
        rasters = input_raster.split(";")
        value_table = []
        for raster in rasters:
            # default name is just the label, prepend 'R_'
            (label, input_ext) = os.path.splitext(os.path.basename(raster))
            label = "R_{0}".format(label)
            value_table.append([raster, label])
        utils.msg("generated value table: %s" % value_table)
        utils.msg("Running ExtractMultiValuesToPoints...")
        ExtractMultiValuesToPoints(selected_layer, value_table, bilinear)
        utils.msg("Values successfully extracted")  
          
# when executing as a standalone script get parameters from sys
if __name__=='__main__':
    # Defaults when no configuration is provided
    defaults_tuple = (
        ('input_raster', os.path.join(settings.example_gdb, "etopop1_downsampled_clipped")),
        ('selected_layer', os.path.join(settings.example_gdb, "SRGD_example_Spatial")),
        ('interpolate', False)
    )

    defaults = utils.parameters_from_args(defaults_tuple, sys.argv)
    main(mode='script', **defaults)
