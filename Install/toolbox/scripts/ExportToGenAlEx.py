# ---------------------------------------------------------------------------
# ExportGenAlEx.py
#
# Created by: Dori Dick
#             College of Earth, Ocean and Atmospheric Sciences
#             Oregon State Univeristy
#
# Created on: 19 March 2012
#  
# Description: This script exports a feature class containing spatially 
#              referenced genetic into the text file format required by 
#              GenAlEx (Peakall and Smouse 2006), an MS Excel Add-In created
#              to run various genetic analyses in Excel.  GenAlEx is 
#              available at: http://www.anu.edu.au/BoZo/GenAlEx/
#
# Required Inputs: An existing Feature Class containing spatially referenced 
#                  genetic data for additional analysis in GenAlEx.
#
# Optional Inputs: A Where Clause option using a SQL Expression to identify 
#                  only those rows with genetic data in the Feature Class.  
#
#            NOTE: This parameter is optional and was included because some 
#                  data sets may have individual IDs based on more than just
#                  genetics (i.e. photo-id).  
#
#                  An Attribute Field that distinguishes the populations in
#                  the Input Feature Class.

#            NOTE: This parameter is optional and was included because
#                  some data sets may have more than one population in it.  
#
# Script Outputs:  A delimited text file formatted to match the required 
#                  input for GenAlEx.
#              
# This script was developed and tested on ArcGIS 10.1 and Python 2.7.
#
# --------------------------------------------------------------------------

import arcpy
import os
import re
import sys
import time
from collections import OrderedDict

# local imports
import utils
import config

def main(input_features=None, where_clause=None, order_by=None, 
        output_name=None):

    # The Input Feature Class
    # == input_features
        
    # Where clause that can be used to pull out only those rows with genetic
    # data from the feature class.

    # NOTE: This parameter is optional and was included because some data 
    # sets may have individual IDs based on more than just genetics 
    # (i.e. photo-id).  If your data only has genetic records, this 
    # parameter can be left blank.
    # == where_clause 

    # The Attribute Field that distinguishes the populations in the input.

    # NOTE: This parameter is optional and was included because some data 
    # sets may have more than one population in it. 
    # == order_by 
       
    try:    
        # Create and open the text file to which the data will be written
        output_file = open(output_name, "w")
    except Exception as e:
        utils.msg("Unable to open text file", mtype='error', exception=e)
    
    utils.msg("Output file open and ready for data input")
            
    # Find our Loci columns. 
    loci = OrderedDict() 
    loci_columns = []
    genetic_columns = config.settings.genetic_columns.split(";")
    loci_expr = '^l_(.*)_[0-9]+'
    for field in [f.name for f in arcpy.ListFields(input_features)]:
        match = re.match(loci_expr, field, re.IGNORECASE)
        if match:
            name = match.groups()[0]
            if loci.has_key(name):
                loci[name].append(field)
            else:
                loci[name] = [field] 
            loci_columns.append(field)

    utils.msg("loci set: {0}".format(",".join(loci.keys())))
    """
    header row contains (in order): 
     - number of loci
     - number of samples
     - number of populations
     - size of pop 1
     - size of pop 2
     - ...
    
    second row contains:
     - three blank cells
     - loci 1 label
     - loci 2 label
     - ...
    
    DATA starts at C4. See "GenAlEx Guide.pdf" page 15.
    """

    # sql clause can be prefix or suffix; set up ORDER BY
    sql_clause = (None, "ORDER BY {0} ASC".format(order_by))
    # query the input_features in ascending order; filtering as needed
    selected_columns = order_by
    pops = OrderedDict()
    rows = arcpy.da.SearchCursor(input_features, selected_columns, where_clause, "", "", sql_clause)
    row_count = 0
    for row in rows:
        row_count += 1
        pop = row[0]
        if pops.has_key(pop):
            pops[pop] +=1
        else:
            pops[pop] = 1

    pop_counts = ",".join([str(p) for p in pops.values()])
    # Creating the GenAlEx header information required for the text file. 
    output_file.write("{0},{1},{2},{3}\n".format(len(loci.keys()),row_count,len(pops.keys()),pop_counts))
   
    # optional title, then a list of each population
    output_file.write(",,,{0}\n".format(",".join(pops.keys())))

    loci_labels = ""
    for (key, cols) in loci.items():
        loci_labels += key
        loci_labels += ","*len(cols)

    output_file.write("{0},{1},{2},{3},{4}\n".format(config.settings.id_field, order_by, loci_labels, config.settings.x_coord, config.settings.y_coord))

    utils.msg("Header info written to text file")

    # Note the WhereClause: Because the SPLASH data has both photo-id and genetic records, but GenAlEx only uses genetic data, the 
    # WhereClause is used to ensure only those records with genetic data are copied to the text file. 
    selected_columns = loci_columns + [config.settings.x_coord, config.settings.y_coord, config.settings.id_field, order_by]
    rows = arcpy.da.SearchCursor(input_features, selected_columns, where_clause, "", "", sql_clause)
    for row in rows:
        pop = row[-1] # last column is 'order_by', or key column
        id_field = row[-2] # as set on import
        y = row[-3]
        x = row[-4]
        result_row = [id_field, pop]

        for (key, cols) in loci.items():
            for col in cols:
                col_pos = selected_columns.index(col)
                result_row.append(row[col_pos])
        result_row = result_row + ["", x, y]
        output_file.write(",".join([str(s) for s in result_row]) + "\n")

    utils.msg("Exported results saved to %s." % output_name)
    time.sleep(4)

    # Close Output text file
    output_file.close()

if __name__ == 'main':
    # Defaults when no configuration is provided
    # TODO: change these to be test-based.
    defaults_tuple = (
        ('input_features', 
        "C:\\geneGIS\\WorkingFolder\\test_20March.gdb\\SPLASH_Whales"),
        ('where_clause', "Individual_ID" + "<>'" + str("")+"'"),
        ('order_by', 'Area'),
        ('output_location',  "C:\\geneGIS\\WorkingFolder\\GenAlEx_Codominant_Export")
    )

    defaults = utils.parameters_from_args(defaults_tuple, sys.argv)
    main(*defaults.values(), mode='script')
