import os
import sys
import re
import pandas as pd
import numpy as np
from natsort import natsorted
import config.ckg_config as ckg_config
import ckg_utils
from graphdb_connector import connector
from graphdb_builder import builder_utils
from graphdb_builder.experiments import experiments_controller as eh
from report_manager.queries import query_utils
from apps import projectCreation as pc
import logging
import logging.config

log_config = ckg_config.graphdb_builder_log
logger = builder_utils.setup_logging(log_config, key="data_upload")


try:
	cwd = os.path.abspath(os.path.dirname(__file__))
	config = builder_utils.setup_config('experiments')
except Exception as err:
	logger.error("Reading configuration > {}.".format(err))


def get_data_upload_queries():
	"""
    Reads the YAML file containing the queries relevant to parsing of clinical data and \
    returns a Python object (dict[dict]).
	
	:return: Nested dictionary.
	"""
	try:
		queries_path = "../queries/data_upload_cypher.yml"
		data_upload_cypher = ckg_utils.get_queries(os.path.join(cwd, queries_path))
	except Exception as err:
		exc_type, exc_obj, exc_tb = sys.exc_info()
		fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
		logger.error("Reading queries from file {}: {}, file: {},line: {}".format(queries_path, sys.exc_info(), fname, exc_tb.tb_lineno))
	return data_upload_cypher

def get_new_biosample_identifier(driver):
	"""
	Queries the database for the last biological sample internal identifier and returns a new sequential identifier.
	
	:param driver: py2neo driver, which provides the connection to the neo4j graph database.
    :type driver: py2neo driver
	:return: Biological sample identifier.
    :rtype: str
	"""
	query_name = 'increment_biosample_id'
	try:
		cypher = get_data_upload_queries()
		query = cypher[query_name]['query']
		identifier = connector.getCursorData(driver, query).values[0][0]
	except Exception as err:
		exc_type, exc_obj, exc_tb = sys.exc_info()
		fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
		logger.error("Reading query {}: {}, file: {},line: {}".format(query_name, sys.exc_info(), fname, exc_tb.tb_lineno))
	return identifier

def get_new_analytical_sample_identifier(driver):
	"""
	Queries the database for the last analytical sample internal identifier and returns a new sequential identifier.
	
	:param driver: py2neo driver, which provides the connection to the neo4j graph database.
    :type driver: py2neo driver
	:return: Analytical sample identifier.
	:rtype: str
	"""
	query_name = 'increment_analytical_sample_id'
	try:
		cypher = get_data_upload_queries()
		query = cypher[query_name]['query']
		identifier = connector.getCursorData(driver, query).values[0][0]
	except Exception as err:
		exc_type, exc_obj, exc_tb = sys.exc_info()
		fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
		logger.error("Reading query {}: {}, file: {},line: {}".format(query_name, sys.exc_info(), fname, exc_tb.tb_lineno))
	return identifier

def get_subject_number_in_project(driver, projectId):
	"""
	Extracts the number of subjects included in a given project.
	
	:param driver: py2neo driver, which provides the connection to the neo4j graph database.
    :type driver: py2neo driver
	:param str projectId: external project identifier (from the graph database).
	:return: Integer with the number of subjects.
	"""
	query_name = 'subject_number'
	try:
		cypher = get_data_upload_queries()
		query = cypher[query_name]['query']
		result = connector.getCursorData(driver, query, parameters={'external_id':projectId}).values[0][0]
	except Exception as err:
		exc_type, exc_obj, exc_tb = sys.exc_info()
		fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
		logger.error("Reading query {}: {}, file: {},line: {}".format(query_name, sys.exc_info(), fname, exc_tb.tb_lineno))
	return result

def create_new_biosamples(driver, projectId, data):
	"""
	Creates new graph database nodes and relationships for biological samples obtained from subjects participating in a project.
	
	:param driver: py2neo driver, which provides the connection to the neo4j graph database.
    :type driver: py2neo driver
	:param str projectId: external project identifier (from the graph database).
	:param data: pandas Dataframe with clinical data as columns and samples as rows.
	:return: Pandas DataFrame where new biological sample internal identifiers have been added.
	"""
	query_name = 'create_biosample'
	biosample_dict = {}
	done = 0
	try:
		df = data[[i for i in data.columns if str(i).startswith('biological_sample') or str(i).startswith('subject')]]
		df.columns=[col.replace('biological_sample ', '').replace(' ','_') for col in df.columns]
		cypher = get_data_upload_queries()
		query = cypher[query_name]['query']
		for bio_external_id in data['biological_sample external_id'].unique():
			biosample_id = get_new_biosample_identifier(driver)
			biosample_dict[bio_external_id] = biosample_id

			mask = df[df['external_id'] == bio_external_id]
			parameters = mask.to_dict(orient='records')[0]
			parameters['biosample_id'] = str(biosample_id)

			for q in query.split(';')[0:-1]:
				if '$' in q:
					result = connector.getCursorData(driver, q+';', parameters=parameters)
				else:
					result = connector.getCursorData(driver, q+';')
			done += 1
	except Exception as err:
		exc_type, exc_obj, exc_tb = sys.exc_info()
		fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
		logger.error("Reading query {}: {}, file: {},line: {}".format(query_name, sys.exc_info(), fname, exc_tb.tb_lineno))

	data.insert(1, 'biological_sample id', data['biological_sample external_id'].map(biosample_dict))
	return data

def create_new_ansamples(driver, projectId, data):
	"""
	Creates new graph database nodes and relationships for analytical samples obtained.
	
	:param driver: py2neo driver, which provides the connection to the neo4j graph database.
    :type driver: py2neo driver
	:param str projectId: external project identifier (from the graph database).
	:param data: pandas Dataframe with clinical data as columns and samples as rows.
	:return: Pandas DataFrame where new analytical sample internal identifiers have been added.
	"""
	query_name = 'create_analytical_sample'
	ansample_dict = {}
	done = 0
	try:
		df = data[[i for i in data.columns if str(i).startswith('analytical_sample')]]
		df.columns=[col.replace('analytical_sample ', '').replace(' ','_') for col in df.columns]
		df['biosample_id'] = data['biological_sample id']
		df['group'] = data['grouping1']
		df['secondary_group'] = data['grouping2']
		cypher = get_data_upload_queries()
		query = cypher[query_name]['query']
		for an_external_id in data['analytical_sample external_id'].unique():
			ansample_id = get_new_analytical_sample_identifier(driver)
			ansample_dict[an_external_id] = ansample_id
			
			mask = df[df['external_id'] == an_external_id]
			parameters = mask.to_dict(orient='records')[0]
			parameters['ansample_id'] = str(ansample_id)
			for q in query.split(';')[0:-1]:
				if '$' in q:
					result = connector.getCursorData(driver, q+';', parameters=parameters)
				else:
					result = connector.getCursorData(driver, q+';')
			done += 1
	except Exception as err:
		exc_type, exc_obj, exc_tb = sys.exc_info()
		fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
		logger.error("Reading query {}: {}, file: {},line: {}".format(query_name, sys.exc_info(), fname, exc_tb.tb_lineno))

	data.insert(2, 'analytical_sample id', data['analytical_sample external_id'].map(ansample_dict))
	return data	

def create_new_experiment_in_db(driver, projectId, data, separator='|'):
	"""
	Creates a new project in the graph database, following the steps:
    
	1. Maps intervention, disease and tissue names to database identifiers and adds data to \
		pandas DataFrame.
	2. Creates new biological and analytical samples.
	3. Checks if the number of subjects created in the graph database matches the number of \
		subjects in the input dataframe.
	4. Saves all the relevant node and relationship dataframes to tab-delimited files.

	:param driver: py2neo driver, which provides the connection to the neo4j graph database.
    :type driver: py2neo driver
	:param str projectId: external project identifier (from the graph database).
	:param data: pandas Dataframe with clinical data as columns and samples as rows.
	:param str separator: character used to separate multiple entries in an attribute.
	:return: Pandas Dataframe with all clinical data and graph database internal identifiers.
	"""
	tissue_dict = {}
	disease_dict = {}
	intervention_dict = {}

	for disease in data['disease'].dropna().unique():
		if len(disease.split(separator)) > 1:
			ids = []
			for i in disease.split(separator):
				disease_id = query_utils.map_node_name_to_id(driver, 'Disease', str(i))
				ids.append(disease_id)
			disease_dict[disease] = '|'.join(ids)
		else:
			disease_id = query_utils.map_node_name_to_id(driver, 'Disease', str(disease))
			disease_dict[disease] = disease_id

	for tissue in data['tissue'].dropna().unique():
		tissue_id = query_utils.map_node_name_to_id(driver, 'Tissue', str(tissue))
		tissue_dict[tissue] = tissue_id

	for interventions in data['intervention'].dropna().unique():
		for intervention in interventions.split('|'):
			intervention_dict[intervention] = re.search('\(([^)]+)', intervention.split()[-1]).group(1)

	data.insert(1, 'intervention id', data['intervention'].map(intervention_dict))
	data.insert(1, 'disease id', data['disease'].map(disease_dict))
	data.insert(1, 'tissue id', data['tissue'].map(tissue_dict))

	df = create_new_biosamples(driver, projectId, data)

	df2 = create_new_ansamples(driver, projectId, df)

	project_subjects = get_subject_number_in_project(driver, projectId)
	dataRows = df2[['subject id', 'subject external_id']].dropna(axis=0)
	dataRows = dataRows.drop_duplicates(keep='first').reset_index(drop=True)
	dataRows.columns = ['ID', 'external_id']
	if int(project_subjects) != len(dataRows['ID'].unique()):
		dataRows = None
	if dataRows is not None:
		generateGraphFiles(dataRows,'subjects', projectId, d='clinical')
	dataRows = eh.extractBiologicalSampleSubjectRelationships(df2)
	if dataRows is not None:
		generateGraphFiles(dataRows,'subject_biosample', projectId, d='clinical')
	dataRows = eh.extractBiologicalSamplesInfo(df2)
	if dataRows is not None:
		generateGraphFiles(dataRows,'biological_samples', projectId, d='clinical')
	dataRows = eh.extractAnalyticalSamplesInfo(df2)
	if dataRows is not None:
		generateGraphFiles(dataRows,'analytical_samples', projectId, d='clinical')
	dataRows = eh.extractBiologicalSampleAnalyticalSampleRelationships(df2)
	if dataRows is not None:
		generateGraphFiles(dataRows,'biosample_analytical', projectId, d='clinical')
	dataRows = eh.extractBiologicalSampleTimepointRelationships(df2)
	if dataRows is not None:
		generateGraphFiles(dataRows,'biological_sample_at_timepoint', projectId, d='clinical')
	dataRows = eh.extractBiologicalSampleTissueRelationships(df2)
	if dataRows is not None:
		generateGraphFiles(dataRows,'biosample_tissue', projectId, d='clinical')
	dataRows = eh.extractSubjectDiseaseRelationships(df2, separator=separator)
	if dataRows is not None:
		generateGraphFiles(dataRows,'disease', projectId, d='clinical')
	dataRows = eh.extractBiologicalSampleGroupRelationships(df2)
	if dataRows is not None:
		generateGraphFiles(dataRows,'groups', projectId, d='clinical')
	dataRows1, dataRows2 = eh.extractBiologicalSampleClinicalVariablesRelationships(df2)
	if dataRows is not None:
		generateGraphFiles(dataRows1,'clinical_state', projectId, d='clinical')
		generateGraphFiles(dataRows2,'clinical_quant', projectId, d='clinical')
	return df2


def generateGraphFiles(data, dataType, projectId, ot = 'w', d = 'proteomics'):
	"""
	Saves data provided as a Pandas DataFrame to a tab-delimited file.
	
	:param data: pandas DataFrame.
	:param str dataType: type of data in 'data'.
	:param str projectId: external project identifier (from the graph database).
	:param str ot: mode while opening file.
	:param str d: data type ('proteomics', 'clinical', 'wes').
	"""
	importDir = os.path.join('../../data/imports/experiments', os.path.join(projectId,d))
	ckg_utils.checkDirectory(importDir)
	outputfile = os.path.join(importDir, projectId+"_"+dataType.lower()+".tsv")
	with open(outputfile, ot) as f:
		data.to_csv(path_or_buf = f, sep='\t',
					header=True, index=False, quotechar='"',
					line_terminator='\n', escapechar='\\')
	logger.info("Experiment {} - Number of {} relationships: {}".format(projectId, dataType, data.shape[0]))

