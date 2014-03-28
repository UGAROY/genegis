# -*- coding: utf-8 -*-

import os
import re
import sys
import time

import xml.etree.cElementTree as et
import glob

import arcpy

# enable local imports; allow importing both this directory and one above
local_path = os.path.dirname(__file__)
for path in [local_path, os.path.join(local_path, '..')]:
    full_path = os.path.abspath(path)
    sys.path.insert(0, os.path.abspath(path))

# addin specific configuration and utility functions
import utils as addin_utils
import config

# import utilities & config from our scripts as well
from scripts import utils

# import our datatype conversion submodule
from datatype import datatype
dt = datatype.DataType()

# NOTE: setting the output to a geodatabase feature class is really expensive;
# the two uses of this call in the initialization code make opening the toolbox
# take 6+ sec longer.
def selected_layer():
    selected_layer = None
    current_layers = addin_utils.currentLayers()
    # just keep the layer list?
    if len(current_layers) > 0:
        # FIXME: do something better here.
        selected_layer = None
    else:
        # check if we have a layer selected from the combo box
        if config.selected_layer is not None:
            selected_layer = config.selected_layer.dataSource
        elif config.settings.fc_path != '':
            selected_layer = config.settings.fc_path
    return selected_layer

# get rid of problematical tags for revision control.
def metadata(update=True):
    if not update:
        try:
            pyt_xmls = glob.glob(os.path.join(local_path, "*.pyt.xml"))
            for xml_path in pyt_xmls:
                tree = et.parse(xml_path)
                esri = tree.find('Esri')
                mod_date = esri.find('ModDate')
                mod_time = esri.find('ModTime')
                if mod_date is not None:
                    esri.remove(mod_date)
                if mod_time is not None:
                    esri.remove(mod_time)
                tree.write(xml_path)
        except Exception as e:
            pass


class Toolbox(object):
    def __init__(self):
        self.label = u'geneGIS_Jan_2013'
        self.alias = ''
        self.tools = [
            ClassifiedImport, # import data from SRGD file
            SelectDataByAttributes, # filter data
            # Geographic Analysis
            ExtractRasterByPoints, # extract values at point locations
            DistanceMatrix,
            ShortestDistancePaths,
            MakeIndividualPaths,
            # Genetic Analysis
            SpagediFst,
            # Export routines; get our data elsewhere
            ExportAllelesInSpace, # Alleles in Space, spatial/genetic analysis
            ExportGenAlEx, # GenAlEx, Excel analysis tool
            ExportGenepop, # Genepop, population differentiation statistics
            ExportSpagedi, # SPAGeDi, fancy genetic statistics package
            ExportSRGD # SRGD w/o Geodatabase columns; for Shepard interchange
        ]

# Tool implementation code
class ClassifiedImport(object):

    def __init__(self):
        self.label = u'Import Data'
        self.description = u'This tool allows the user to covert an input file (a text file or Excel spreadsheet formated with the SRGD specifications) to a feature class within a file geodatabase.'
        self.canRunInBackground = False
        self.category = "Import"
        # perform some dynamic list filtering, in the case that we have a
        # table input selected.
        self.cols = {
            'input_csv': 0,
            'sr': 1,
            'output_loc': 2,
            'output_gdb': 3,
            'output_fc': 4,
            'Genetic': 5,
            'Identification': 6,
            'Location': 7,
            'Other': 8
        }
        # one of the tools needs to have the metadata deletion call included in it. If it's done elsewhere
        # in the script, the script state isn't correct and the ModTime and ModDate fields will remain.
        metadata(update=False)

    def getParameterInfo(self):
        # SRGD_Input_File
        input_csv = arcpy.Parameter()
        input_csv.name = u'SRGD_Input_File'
        input_csv.displayName = u'SRGD Input File'
        input_csv.parameterType = 'Required'
        input_csv.direction = 'Input'
        input_csv.datatype = dt.format('File')

        # Spatial_Reference
        sr = arcpy.Parameter()
        sr.name = u'Spatial_Reference'
        sr.displayName = u'Spatial Reference'
        sr.parameterType = 'Optional'
        sr.direction = 'Input'
        sr.datatype = dt.format('Spatial Reference')

        # File_Geodatabase_Location
        output_loc= arcpy.Parameter()
        output_loc.name = u'File_Geodatabase_Location'
        output_loc.displayName = u'File Geodatabase Location'
        output_loc.parameterType = 'Required'
        output_loc.direction = 'Input'
        output_loc.datatype = dt.format('Folder')

        # File_Geodatabase_Name
        output_gdb= arcpy.Parameter()
        output_gdb.name = u'File_Geodatabase_Name'
        output_gdb.displayName = u'File Geodatabase Name'
        output_gdb.parameterType = 'Required'
        output_gdb.direction = 'Input'
        output_gdb.datatype = dt.format('String')

        # Output_Feature_Class
        output_fc= arcpy.Parameter()
        output_fc.name = u'Output_Feature_Class'
        output_fc.displayName = u'Output Feature Class'
        output_fc.parameterType = 'Derived'
        output_fc.direction = 'Output'
        output_fc.datatype = dt.format('DEFeatureClass')
        output_fc.parameterDependencies = [output_loc.name, output_gdb.name]

        # genetic columns
        genetic = arcpy.Parameter()
        genetic.name = u'Genetic_Columns'
        genetic.displayName = u'Genetic Columns'
        genetic.parameterType = 'Required'
        genetic.direction = 'Input'
        genetic.multiValue = True
        genetic.filter.list = ['Sex', 'Haplotype', 'L_locus1', 'L_locus2']

        # identification columns
        identification = arcpy.Parameter()
        identification.name = 'Identification_Columns'
        identification.displayName = 'Identification Columns'
        identification.parameterType = 'Required'
        identification.direction = 'Input'
        identification.multiValue = True
        identification.filter.list = ['Sample_ID', 'Individual_ID']

        # location columns
        loc = arcpy.Parameter()
        loc.name = u'Location_Columns'
        loc.displayName = u'Location Columns'
        loc.parameterType = 'Required'
        loc.direction = 'Input'
        loc.multiValue = True
        loc.filter.list = ['Latitude', 'Longitude']

        # other columns
        other = arcpy.Parameter()
        other.name = u'Other_Columns'
        other.displayName = u'Other Columns'
        other.parameterType = 'Optional'
        other.direction = 'Input'
        other.multiValue = True
        other.filter.list = ['Region', 'Date_Time']

        return [input_csv, sr, output_loc, output_gdb, output_fc, \
                genetic, identification, loc, other]

    def isLicensed(self):
        return True

    def updateDynamicFilters(self, filter_param, update_param, unused_values):
        result = []
        # ValueTable object;
        # http://help.arcgis.com/en/arcgisdesktop/10.0/help/000v/000v000000q1000000.htm
        filter_val = filter_param.value
        if filter_val is not None:
            filter_values = filter_val.exportToString().split(";")

            for param in unused_values:
                if param not in filter_values:
                    result.append(param)

            update_param.filter.list = result
        return result

    def updateParameters(self, parameters):
        unused_values = []

        input_table_name = parameters[self.cols['input_csv']].valueAsText
        output_loc = parameters[self.cols['output_loc']].valueAsText
        output_gdb = parameters[self.cols['output_gdb']].valueAsText
        output_fc = parameters[self.cols['output_fc']].valueAsText

        if input_table_name is not None:
            # read the validated header
            (header, data, dialect) = utils.validated_table_results(input_table_name)
            # create a duplicate list; but a copy so we can modify the list as we go
            unused_values = list(header)

            dynamic_cols = ['Genetic', 'Identification', 'Location', 'Other']
            # A little tricky: implement unique result lists for each of
            # our group types.
            results = dict(((group,[]) for group in dynamic_cols))
            for (group, expr, data_type) in config.group_expressions:
                for (i, value) in enumerate(header):
                    if re.search(expr, value, re.IGNORECASE):
                        results[group].append(value)
                        unused_values.remove(value)
                        # if a data type is defined for this column,
                        # record it so we can force a mapping on import.
                        if data_type is not None:
                            if isinstance(data_type, str):
                                forced_type = data_type
                            else: 
                                # if we have multiple values in the data type,
                                # examine the data to determine which'd be best.
                                preferred_type = data_type[0]
                                data_sample = data[0][i]
                                if preferred_type == 'Integer':
                                    try:
                                        int(data_sample)
                                        forced_type = preferred_type
                                    except:
                                        # fall back to the default type
                                        forced_type = data_type[1]

                            config.protected_columns[value] = (i + 1, forced_type)

            # any remaining attributes should be included under 'Other'
            results['Other'] = unused_values

            # update the lists provided to the user
            for (group, vals) in results.items():
                parameters[self.cols[group]].filter.list = vals
                parameters[self.cols[group]].value = vals

        if output_loc is not None and input_table_name is not None and output_gdb is not None:
            # derive the output feature class name if these two parameters are set
            (label, ext) = os.path.splitext(os.path.basename(input_table_name))
            output_fc_path = os.path.join(output_loc, "%s.gdb" % output_gdb, "%s_Spatial" % label)
            parameters[self.cols['output_fc']].value = output_fc_path

        """
        for i, label in enumerate(dynamic_cols[1:]):
            update_label = self.cols[label]
            filter_label = self.cols[dynamic_cols[i]]
            #f.write("Running with: {0} {1} {2}\n\n".format(update_label,
            #    filter_label, ",".join(unused_values)))
            unused_values = self.updateDynamicFilters(
                    parameters[filter_label],
                    parameters[update_label],
                    unused_values)
        """
        return

    def updateMessages(self, parameters):
        input_table_name = parameters[self.cols['input_csv']].valueAsText
        if input_table_name is not None:
            # read the original data
            (orig_header, orig_data, orig_dialect) = utils.parse_table(input_table_name)
            # read the validated header
            (header, data, dialect) = utils.validated_table_results(input_table_name)

            # check if we've modified the header.
            if orig_header != header:
                modified_columns = []
                # find which columns have been changed
                for (i, column) in enumerate(header):
                    orig_column = orig_header[i]
                    if orig_column != column:
                        modified_columns.append((orig_column, column))
                modified_result = [" was modified to ".join(c) for c in modified_columns]
                msg = "Headers were modified based on File Geodatabase field name restrictions:\n" \
                      + "\n".join(modified_result)
                parameters[0].setWarningMessage(msg)
        return

    def execute(self, parameters, messages):
        from scripts import ClassifiedImport

        # if the script is running within ArcGIS as a tool, get the following
        # user defined parameters
        ClassifiedImport.main(
            input_table=parameters[0].valueAsText,
            sr=parameters[1].valueAsText,
            output_loc=parameters[2].valueAsText,
            output_gdb=parameters[3].valueAsText,
            output_fc=parameters[4].valueAsText,
            genetic=parameters[5].valueAsText,
            identification=parameters[6].valueAsText,
            location=parameters[7].valueAsText,
            other=parameters[8].valueAsText,
            protected_map=config.protected_columns)

        return

class ExtractRasterByPoints(object):
    def __init__(self):
        self.label = u'Extract Raster Values To Points'
        self.description = u'This tool allows extraction of one or more rasters at our sample locations.'
        self.canRunInBackground = False
        self.category = "Analysis"
        self.cols = {
            'input_raster': 0,
            'input_fc': 1
        }

    def getParameterInfo(self):
        # FIXME: Doesn't run if the user hasn't selected a layer in the combobox. Either throw an error before they run the tool, or let them fill it out, but populate it if they've selected a layer.

        # Raster Input
        input_raster = arcpy.Parameter()
        input_raster.name = u'Input_Raster'
        input_raster.displayName = u'Input Raster(s)'
        input_raster.parameterType = 'Required'
        input_raster.direction = 'Input'
        input_raster.datatype = dt.format('Raster Dataset')
        input_raster.multiValue = True

        # Output Feature Class
        input_fc = arcpy.Parameter()
        input_fc.name = u'Input_Feature_Class'
        input_fc.displayName = u'Feature Class (will add columns for extracted raster results)'
        input_fc.direction = 'Input'
        input_fc.parameterType = 'Required'
        input_fc.datatype = dt.format('Feature Class')
        #input_fc.value = selected_layer()

        return [input_raster, input_fc]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        from scripts import ExtractRasterValuesToPoints

        # if the script is running within ArcGIS as a tool, get the following
        # user defined parameters
        ExtractRasterValuesToPoints.main(
            input_raster=parameters[0].valueAsText,
            selected_layer=parameters[1].valueAsText)

class ShortestDistancePaths(object):
    def __init__(self):
        self.label = u'Geographic Distance Paths'
        self.description = u'Calculate the pairwise shortest distance paths between all observations'
        self.canRunInBackground = False
        self.category = "Analysis"
        self.cols = {
            'input_fc': 0,
            'output_fc': 1,
            'closest': 2
        }

    def getParameterInfo(self):

        # Input Feature Class
        input_fc = arcpy.Parameter()
        input_fc.name = u'Input_Feature_Class'
        input_fc.displayName = u'Feature Class'
        input_fc.direction = 'Input'
        input_fc.parameterType = 'Required'
        input_fc.datatype = dt.format('Feature Layer')
        #input_fc.value = selected_layer()

        # Output Feature Class
        output_fc = arcpy.Parameter()
        output_fc.name = u'Output_Feature_Class'
        output_fc.displayName = u'Output Feature Class'
        output_fc.direction = 'Output'
        output_fc.parameterType = 'Required'
        output_fc.datatype = dt.format('Feature Layer')

        # limit to the closest observation
        closest = arcpy.Parameter()
        closest.name = 'Closest_Count'
        closest.displayName = 'Find only closest feature'
        closest.direction = 'Input'
        closest.parameterType = 'Optional'
        closest.datatype = dt.format('Boolean')

        return [input_fc, output_fc, closest]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        from scripts import ShortestDistancePaths

        ShortestDistancePaths.main(
            input_fc=parameters[0].valueAsText,
            output_fc=parameters[1].valueAsText,
            closest=parameters[2].valueAsText)

class DistanceMatrix(object):
    def __init__(self):
        self.label = u'Geographic Distance Matrix'
        self.description = u'Calculate the geographic distance matrix between all locations'
        self.canRunInBackground = False
        self.category = "Analysis"
        self.cols = {
            'input_fc': 0,
            'dist_units' : 1,
            'matrix_type': 2,
            'output_matrix': 3
        }
        self.display_units = config.distance_units.keys()

    def getParameterInfo(self):
        # Input Feature Class
        input_fc = arcpy.Parameter()
        input_fc.name = u'Input_Feature_Class'
        input_fc.displayName = u'Feature Class'
        input_fc.direction = 'Input'
        input_fc.parameterType = 'Required'
        input_fc.datatype = dt.format('Feature Layer')
        #input_fc.value = selected_layer()

        # Matrix units
        dist_unit = arcpy.Parameter()
        dist_unit.name = 'Distance_Units'
        dist_unit.displayName = 'Distance Units'
        dist_unit.direction = 'Input'
        dist_unit.parameterType = 'Required'
        dist_unit.datatype = dt.format('String')
        dist_unit.filter.list = self.display_units
        dist_unit.value = self.display_units[0]

        # Matrix Type
        matrix_type = arcpy.Parameter()
        matrix_type.name = 'Matrix_Type'
        matrix_type.displayName = 'Matrix Type'
        matrix_type.direction = 'Input'
        matrix_type.parameterType = 'Required'
        matrix_type.datatype = dt.format('String')
        #matrix_type.filter.list = ['Pairwise', 'Square']
        matrix_type.filter.list = ['Square', 'Square (SPAGeDi formatted)']
        matrix_type.value = 'Square'

        # Output Matrix
        output_matrix= arcpy.Parameter()
        output_matrix.name = u'Output_Matrix'
        output_matrix.displayName = u'Output Matrix'
        output_matrix.direction = 'Output'
        output_matrix.parameterType = 'Required'
        output_matrix.datatype = dt.format('File')

        return [input_fc, dist_unit, matrix_type, output_matrix]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        output_matrix = parameters[self.cols['output_matrix']]
        output_matrix.value = utils.set_file_extension(output_matrix, 'csv')
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        from scripts import DistanceMatrix

        DistanceMatrix.main(
            input_fc=parameters[0].valueAsText,
            dist_unit=parameters[1].valueAsText,
            matrix_type=parameters[2].valueAsText,
            output_matrix=parameters[3].valueAsText)

""" Genetic Analysis """

class SpagediFst(object):
    def __init__(self):
        self.label = u'Genetic Analysis - F_st'
        self.description = u'Calculate F_st using Jacknifing'
        self.canRunInBackground = False
        self.category = "Analysis"
        self.cols = {
            'input_fc': 0,
            'order_by': 1,
            'analysis_type': 2,
            'output_file': 3
        }

    def getParameterInfo(self):

        # Input Feature Class
        input_fc = arcpy.Parameter()
        input_fc.name = u'Input_Feature_Class'
        input_fc.displayName = u'Feature Class'
        input_fc.direction = 'Input'
        input_fc.parameterType = 'Required'
        input_fc.datatype = dt.format('Feature Layer')

        # Attribute_Field__to_order_by_population_
        order_by = arcpy.Parameter()
        order_by.name = u'Population Field'
        order_by.displayName = u'Population Field'
        order_by.parameterType = 'Required'
        order_by.direction = 'Input'
        order_by.datatype = dt.format('Field')
        order_by.parameterDependencies=[input_fc.name]

        # Analysis Type
        analysis_type = arcpy.Parameter()
        analysis_type.name = 'Analysis_Type'
        analysis_type.displayName = 'Analysis Type'
        analysis_type.direction = 'Input'
        analysis_type.parameterType = 'Required'
        analysis_type.datatype = dt.format('String')
        analysis_type.filter.list = ['Jacknifing']
        analysis_type.value = 'Jacknifing'

        # Output File
        output_file = arcpy.Parameter()
        output_file.name = u'Output_File'
        output_file.displayName = u'Output Results File'
        output_file.direction = 'Output'
        output_file.parameterType = 'Required'
        output_file.datatype = dt.format('File')

        return [input_fc, order_by, analysis_type, output_file]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        output_file = parameters[self.cols['output_file']]
        output_file.value = utils.set_file_extension(output_file, 'txt')
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        from scripts import ExportToSPAGeDi
        # TODO: from scripts import RunSpagediModel

        results = parameters[3].valueAsText

        # temporary SPAGEDI output file
        spagedi_file_path = os.path.join(config.config_dir, "spagedi_data.txt")

        utils.msg("writing spagedi-formatted results...")

        # compute our spagedi file first
        ExportToSPAGeDi.main(
            input_features=parameters[0].valueAsText,
            where_clause="",
            order_by=parameters[1].valueAsText,
            output_name=spagedi_file_path)

        utils.msg("writing out spagedi commands...")
        # now, generate an input file for SPAGeDi
        spagedi_commands = os.path.join(config.config_dir, "spagedi_commands.txt")
        utils.msg(spagedi_commands)
        with open(spagedi_commands, 'w') as command_file:
            file_string = """{spagedi_file_path}
{results}

2
1
4



""".format(spagedi_file_path=spagedi_file_path, results=results)
            command_file.write(file_string)

        # now, fire up SPAGeDi
        spagedi_msg = """Now running SPAGeDi 1.4a (build 11-01-2013)
   - a program for Spatial Pattern Analysis of Genetic Diversity
               Written by Olivier Hardy & Xavier Vekemans
               Contributions by Reed Cartwright"""
        utils.msg(spagedi_msg)
        time.sleep(2)

        spagedi_executable_path = os.path.abspath( \
                os.path.join(os.path.abspath(os.path.dirname(__file__)), \
                "lib", config.spagedi_executable))

        cmd = "{spagedi_exe} < {spagedi_commands}".format(
                spagedi_exe=spagedi_executable_path,
                spagedi_commands=spagedi_commands)
        utils.msg("trying to run %s" % cmd)

        # TODO replace with subprocess call
        res = os.system(cmd)

        utils.msg("trying to open resulting file %s" % results)
        os.startfile(results)
        utils.msg("all done!")

""" Export data """

class ExportGenAlEx(object):

    def __init__(self):
        self.label = u'Export to GenAlex_CodominantData'
        self.description = u'This tool allows the user to export data to a comma separated text file that follows the required input format for GenAlEx (Peakall and Smouse 2006), a Microsoft Excel Add-In.\r\n\r\nGenAlEx is available from:\r\n\r\nhttp://www.anu.edu.au/BoZo/GenAlEx/\r\n'
        self.canRunInBackground = False
        self.category = "Export"
        self.cols = {
            'input_features': 0,
            'where_clause' : 1,
            'order_by' : 2,
            'output_name': 3
        }

    def getParameterInfo(self):
        # Input_Feature_Class
        input_features = arcpy.Parameter()
        input_features.name = u'Input_Feature_Class'
        input_features.displayName = u'Input Feature Class'
        input_features.parameterType = 'Required'
        input_features.direction = 'Input'
        input_features.datatype = dt.format('Feature Layer')
        #input_features.value = selected_layer()

        # Where_Clause
        where_clause = arcpy.Parameter()
        where_clause.name = u'Where_Clause'
        where_clause.displayName = u'Where Clause'
        where_clause.parameterType = 'Optional'
        where_clause.direction = 'Output'
        where_clause.datatype = dt.format('SQL Expression')
        where_clause.parameterDependencies= [input_features.name]

        # Attribute_Field__to_order_by_population_
        order_by = arcpy.Parameter()
        order_by.name = u'Population Field'
        order_by.displayName = u'Population Field'
        order_by.parameterType = 'Required'
        order_by.direction = 'Input'
        order_by.datatype = dt.format('Field')
        order_by.parameterDependencies=[input_features.name]

        # Output_File_Location
        output_name = arcpy.Parameter()
        output_name.name = u'Output_File'
        output_name.displayName = u'Output File'
        output_name.parameterType = 'Required'
        output_name.direction = 'Output'
        output_name.datatype = dt.format('File')

        return [input_features, where_clause, order_by, output_name]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        output_name = parameters[self.cols['output_name']]
        output_name.value = utils.set_file_extension(output_name, 'csv')
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        from scripts import ExportToGenAlEx
        # if the script is running within ArcGIS as a tool, get the following
        # user defined parameters:
        ExportToGenAlEx.main(
            input_features=parameters[0].valueAsText,
            where_clause=parameters[1].valueAsText,
            order_by=parameters[2].valueAsText,
            output_name=parameters[3].valueAsText)

    arcpy.env.addOutputsToMap  = False

class ExportGenepop(object):

    def __init__(self):
        self.label = u'Export to Genepop'
        self.description = u'This tool allows the user to export data to a text file that follows the required input format for Genepop (Raymond and Rousset 1995; Rousset 2008).  For more information see: \r\n\r\nhttp://genepop.curtin.edu.au/\r\n'
        self.canRunInBackground = False
        self.category = "Export"
        self.cols = {
            'input_features': 0,
            'where_clause': 1,
            'order_by': 2,
            'output_name': 3
        }

    def getParameterInfo(self):
        # Input_Feature_Class
        input_features = arcpy.Parameter()
        input_features.name = u'Input_Feature_Class'
        input_features.displayName = u'Input Feature Class'
        input_features.parameterType = 'Required'
        input_features.direction = 'Input'
        input_features.datatype = dt.format('Feature Layer')

        # Where_Clause
        where_clause = arcpy.Parameter()
        where_clause.name = u'Where_Clause'
        where_clause.displayName = u'Where Clause'
        where_clause.parameterType = 'Optional'
        where_clause.direction = 'Output'
        where_clause.datatype = dt.format('SQL Expression')
        where_clause.parameterDependencies= [input_features.name]

        # Attribute_Field__to_order_by_population_
        order_by = arcpy.Parameter()
        order_by.name = u'Population Field'
        order_by.displayName = u'Population Field'
        order_by.parameterType = 'Required'
        order_by.direction = 'Input'
        order_by.datatype = dt.format('Field')
        order_by.parameterDependencies=[input_features.name]

        # Output_File_Location
        output_name = arcpy.Parameter()
        output_name.name = u'Output_File'
        output_name.displayName = u'Output File'
        output_name.parameterType = 'Required'
        output_name.direction = 'Output'
        output_name.datatype = dt.format('File')

        return [input_features, where_clause, order_by, output_name]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        output_name = parameters[self.cols['output_name']]
        output_name.value = utils.set_file_extension(output_name, 'txt')
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        from scripts import ExportToGenepop

        # if the script is running within ArcGIS as a tool, get the following
        # user defined parameters
        ExportToGenepop.main(
            input_features=parameters[0].valueAsText,
            where_clause=parameters[1].valueAsText,
            order_by=parameters[2].valueAsText,
            output_name=parameters[3].valueAsText)
            
    arcpy.env.addOutputsToMap  = False
    
class ExportSpagedi(object):

    def __init__(self):
        self.label = u'Export to SPAGeDi'
        self.description = u'This tool allows the user to export data to a text file that follows the required input format for SPAGeDi (Hardy and Vekemans).'
        self.canRunInBackground = False
        self.category = "Export"
        self.cols = {
            'input_features': 0,
            'where_clause': 1,
            'order_by': 2,
            'output_name': 3
        }

    def getParameterInfo(self):
        # Input_Feature_Class
        input_features = arcpy.Parameter()
        input_features.name = u'Input_Feature_Class'
        input_features.displayName = u'Input Feature Class'
        input_features.parameterType = 'Required'
        input_features.direction = 'Input'
        input_features.datatype = dt.format('Feature Layer')

        # Where_Clause
        where_clause = arcpy.Parameter()
        where_clause.name = u'Where_Clause'
        where_clause.displayName = u'Where Clause'
        where_clause.parameterType = 'Optional'
        where_clause.direction = 'Output'
        where_clause.datatype = dt.format('SQL Expression')
        where_clause.parameterDependencies= [input_features.name]

        # Attribute_Field__to_order_by_population_
        order_by = arcpy.Parameter()
        order_by.name = u'Population Field'
        order_by.displayName = u'Population Field'
        order_by.parameterType = 'Required'
        order_by.direction = 'Input'
        order_by.datatype = dt.format('Field')
        order_by.parameterDependencies=[input_features.name]

        # Output_File_Location
        output_name = arcpy.Parameter()
        output_name.name = u'Output_File'
        output_name.displayName = u'Output File'
        output_name.parameterType = 'Required'
        output_name.direction = 'Output'
        output_name.datatype = dt.format('File')

        return [input_features, where_clause, order_by, output_name]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        output_name = parameters[self.cols['output_name']]
        output_name.value = utils.set_file_extension(output_name, 'txt')
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        from scripts import ExportToSPAGeDi

        # if the script is running within ArcGIS as a tool, get the following
        # user defined parameters
        ExportToSPAGeDi.main(
            input_features=parameters[0].valueAsText,
            where_clause=parameters[1].valueAsText,
            order_by=parameters[2].valueAsText,
            output_name=parameters[3].valueAsText)

class ExportAllelesInSpace(object):

    def __init__(self):
        self.label = u'Export to Alleles In Space'
        self.description = u'This tool allows the user to export data to two text files, separate coordinate and genetic files, that follow the required input format for Alleles in Space (Miller)'
        self.canRunInBackground = False
        self.category = "Export"
        self.cols = {
            'input_features': 0,
            'id_field': 1,
            'where_clause': 2,
            'output_coords': 3,
            'output_genetics': 4
        }

    def getParameterInfo(self):
        # Input_Feature_Class
        input_features = arcpy.Parameter()
        input_features.name = u'Input_Feature_Class'
        input_features.displayName = u'Input Feature Class'
        input_features.parameterType = 'Required'
        input_features.direction = 'Input'
        input_features.datatype = dt.format('Feature Layer')

        # identification field
        id_field = arcpy.Parameter()
        id_field.name = u'Sample ID Field'
        id_field.displayName = u'Sample ID Field'
        id_field.parameterType = 'Required'
        id_field.direction = 'Input'
        id_field.datatype = dt.format('Field')
        id_field.parameterDependencies=[input_features.name]
        id_field.value = config.settings.id_field

        # Where_Clause
        where_clause = arcpy.Parameter()
        where_clause.name = u'Where_Clause'
        where_clause.displayName = u'Where Clause'
        where_clause.parameterType = 'Optional'
        where_clause.direction = 'Output'
        where_clause.datatype = dt.format('SQL Expression')
        where_clause.parameterDependencies= [input_features.name]

        # Output coordinate information
        output_coords = arcpy.Parameter()
        output_coords.name = u'Output_Coordinates'
        output_coords.displayName = u'Output Coordinates File'
        output_coords.parameterType = 'Required'
        output_coords.direction = 'Output'
        output_coords.datatype = dt.format('File')

        # Output genetics information
        output_genetics= arcpy.Parameter()
        output_genetics.name = u'Output_Genetics'
        output_genetics.displayName = u'Output Genetics File'
        output_genetics.parameterType = 'Required'
        output_genetics.direction = 'Output'
        output_genetics.datatype = dt.format('File')

        return [input_features, id_field, where_clause, output_coords, output_genetics]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        output_coords = parameters[self.cols['output_coords']]
        output_genetics = parameters[self.cols['output_genetics']]
        output_coords.value = utils.set_file_extension(output_coords, 'txt')
        output_genetics.value = utils.set_file_extension(output_genetics, 'txt')
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        from scripts import ExportToAIS

        ExportToAIS.main(
            input_features=parameters[0].valueAsText,
            id_field=parameters[1].valueAsText,
            where_clause=parameters[2].valueAsText,
            output_coords=parameters[3].valueAsText,
            output_genetics=parameters[4].valueAsText)


class SelectDataByAttributes(object):

    def __init__(self):
        self.label = u'Select Data By Attributes'
        self.canRunInBackground = False
        self.category = "Analysis"

    def getParameterInfo(self):
        # Input_Feature_Class
        param_1 = arcpy.Parameter()
        param_1.name = u'Input_Feature_Class'
        param_1.displayName = u'Input Feature Class'
        param_1.parameterType = 'Required'
        param_1.direction = 'Input'
        param_1.datatype = dt.format('Feature Layer')

        # Selection_Type
        param_2 = arcpy.Parameter()
        param_2.name = u'Selection_Type'
        param_2.displayName = u'Selection Type'
        param_2.parameterType = 'Required'
        param_2.direction = 'Input'
        param_2.datatype = dt.format('String')
        param_2.filter.list = [u'NEW_SELECTION']

        # SQL_Expression
        param_3 = arcpy.Parameter()
        param_3.name = u'SQL_Expression'
        param_3.displayName = u'SQL Expression'
        param_3.parameterType = 'Required'
        param_3.direction = 'Input'
        param_3.datatype = dt.format('SQL Expression')

        # Selection_Type_2
        param_4 = arcpy.Parameter()
        param_4.name = u'Selection_Type_2'
        param_4.displayName = u'Selection Type 2'
        param_4.parameterType = 'Optional'
        param_4.direction = 'Input'
        param_4.datatype = dt.format('String')
        param_4.filter.list = [u'ADD_TO_SELECTION', u'SUBSET_SELECTION']

        # SQL_Expression_2
        param_5 = arcpy.Parameter()
        param_5.name = u'SQL_Expression_2'
        param_5.displayName = u'SQL Expression 2'
        param_5.parameterType = 'Optional'
        param_5.direction = 'Input'
        param_5.datatype = dt.format('SQL Expression')

        # Selection_Type_3
        param_6 = arcpy.Parameter()
        param_6.name = u'Selection_Type_3'
        param_6.displayName = u'Selection Type 3'
        param_6.parameterType = 'Optional'
        param_6.direction = 'Input'
        param_6.datatype = dt.format('String')
        param_6.filter.list = [u'ADD_TO_SELECTION', u'SUBSET_SELECTION']

        # SQL_Expression_3
        param_7 = arcpy.Parameter()
        param_7.name = u'SQL_Expression_3'
        param_7.displayName = u'SQL Expression 3'
        param_7.parameterType = 'Optional'
        param_7.direction = 'Input'
        param_7.datatype = dt.format('SQL Expression')

        # Output_Feature_Class_Location
        param_8 = arcpy.Parameter()
        param_8.name = u'Output_Feature_Class_Location'
        param_8.displayName = u'Output Feature Class Location'
        param_8.parameterType = 'Required'
        param_8.direction = 'Input'
        param_8.datatype = dt.format('Workspace')

        # Output_Feature_Class_Name
        param_9 = arcpy.Parameter()
        param_9.name = u'Output_Feature_Class_Name'
        param_9.displayName = u'Output Feature Class Name'
        param_9.parameterType = 'Required'
        param_9.direction = 'Input'
        param_9.datatype = dt.format('String')

        # Log_File_Location
        param_10 = arcpy.Parameter()
        param_10.name = u'Log_File_Location'
        param_10.displayName = u'Log File Location'
        param_10.parameterType = 'Required'
        param_10.direction = 'Input'
        param_10.datatype = dt.format('Folder')

        return [param_1, param_2, param_3, param_4, param_5, param_6, param_7, param_8, param_9, param_10]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        from scripts import SelectByAttributes
        # if the script is running within ArcGIS as a tool, get the following
        # user defined parameters:
        SelectByAttributes.main(
            xx=parameters[0].valueAsText,
            yy=parameters[1].valueAsText,
            zz=parameters[2].valueAsText,
            aa=parameters[3].valueAsText)

class ExportSRGD(object):
    def __init__(self):
        self.label = u'Export to SRGD'
        self.description = u'Export SRGD results (formatted CSV).'
        self.canRunInBackground = False
        self.category = "Export"
        self.cols = {
            'input_feature': 0,
            'output_csv': 1
        }

    def getParameterInfo(self):
        input_feature = arcpy.Parameter()
        input_feature.name = 'Input_Feature'
        input_feature.displayName = 'Input Feature'
        input_feature.parameterType = 'Required'
        input_feature.direction = 'Input'
        input_feature.datatype = dt.format('Feature Layer')

        # Output_CSV
        output_csv= arcpy.Parameter()
        output_csv.name = u'Output_SRGD_File'
        output_csv.displayName = u'Output SRGD CSV File'
        output_csv.parameterType = 'Required'
        output_csv.direction = 'Output'
        output_csv.datatype = dt.format('File')

        return [input_feature, output_csv]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):

        output_csv = parameters[self.cols['output_csv']]
        # make sure the output file name has a CSV extension.
        output_csv.value = utils.set_file_extension(output_csv, 'csv')
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        input_feature = parameters[0].valueAsText
        output_csv = parameters[1].valueAsText
        arcpy.env.addOutputsToMap  = False
        # run export on this feature class.
        messages.addMessage("Running export...")
        addin_utils.writeToSRGD(input_feature, output_csv)
        messages.addMessage("Exported results saved to %s." % output_csv)
        time.sleep(4)

class MakeIndividualPaths(object):
    def __init__(self):
        self.label = u'Individual Paths'
        self.description = u'Connect all Encounters for each Individual'
        self.canRunInBackground = False
        self.category = "Analysis"
        self.cols = {
            'selected_pts': 0,
            'source_fc': 1,
            'output_name': 2
        }

    def getParameterInfo(self):
        # Input Features
        selected_pts = arcpy.Parameter()
        selected_pts.name = u'Selected_Feature_Class'
        selected_pts.displayName = u'Selected Individuals'
        selected_pts.direction = 'Input'
        selected_pts.parameterType = 'Required'
        selected_pts.datatype = dt.format('Feature Layer')

        # Data source
        source_fc = arcpy.Parameter()
        source_fc.name = u'Source_Feature_Class'
        source_fc.displayName = u'Source features (to link with selected individuals)'
        source_fc.direction = 'Input'
        source_fc.parameterType = 'Required'
        source_fc.datatype = dt.format('Feature Layer')

        # Output feature name
        output_name = arcpy.Parameter()
        output_name.name = 'Output_Feature_Class'
        output_name.displayName = u'Output Pathsfeatures '
        output_name.direction = 'Output'
        output_name.parameterType = 'Required'
        output_name.datatype = dt.format('String')

        return [selected_pts, source_fc, output_name]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        source_fc = parameters[self.cols['source_fc']]
        output_name = parameters[self.cols['output_name']]
        if source_fc.altered:
            if output_name.altered is False:
                desc = arcpy.Describe(source_fc.value)
                # path will be set, regardless if this is a layer or a fully specified path
                source_fc_path = desc.path
                if source_fc_path is not None: 
                    output_name.value = os.path.join(source_fc_path, "Paths")
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        from scripts import IndividualPaths

        IndividualPaths.main(
            selected_pts=parameters[0].valueAsText,
            source_fc=parameters[1].valueAsText,
            output_name=parameters[2].valueAsText)
