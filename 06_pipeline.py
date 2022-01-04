# Import libraries
from azureml.core import Environment, Experiment, Model, Workspace
from azureml.core.authentication import InteractiveLoginAuthentication
from azureml.core.runconfig import RunConfiguration
from azureml.data import OutputFileDatasetConfig
from azureml.pipeline.core import Pipeline, ScheduleRecurrence, Schedule
from azureml.pipeline.core.run import PipelineRun
from azureml.pipeline.steps import PythonScriptStep
from azureml.widgets import RunDetails
import os
import requests

#-----WORKSPACE----------------------------------------------------------------#
# Load workspace from config JSON file
ws = Workspace.from_config()
print(ws.name, 'loaded')

#-----DATASET------------------------------------------------------------------#
# Get the training dataset from registered datasets (see ./01_datastores.py)
diabetes_ds = ws.datasets.get('diabetes dataset')

#-----COMPUTE_TARGET-----------------------------------------------------------#
# Define compute target (see ./02_compute.py)
cluster_name = 'ml-sdk-cc'

#-----ENVIRONMENT_SETUP--------------------------------------------------------#
# Get the registered environment (see ./03_envs.py)
registered_env = Environment.get(ws, 'experiment_env')

#-----PIPELINE_SETUP-----------------------------------------------------------#
'''
Azure Machine Learning Pipelines
* Consist of one or more steps
* Can be Python scripts, or specialized steps like a data transfer step copying data from one location to another
* Each step can run in its own compute context

This repo defines a simple pipeline containing two Python script steps:
* First step to pre-process training data
* Second step to use the pre-processed data to train a model
* Reuse is enabled:
    * Usually first step should run every time if the data has changed
    * Subsequent steps are triggered only if the output from step one changes
    * For convenience reuse enables to only run any steps with changed parameter

* Common kinds of step in an Azure Machine Learning pipeline:
    * PythonScriptStep: Runs specified Python script
    * DataTransferStep: Uses Azure Data Factory to copy data between data stores
    * DatabricksStep:   Runs notebook, script, or compiled JAR on a databricks cluster
    * AdlaStep:         Runs U-SQL job in Azure Data Lake Analytics
    * ParallelRunStep:  Runs Python script as a distributed task on multiple compute nodes.
'''
# Define pipeline configuration
pipeline_run_config = RunConfiguration()                        # Create a new runconfig object for the pipeline
pipeline_run_config.target = cluster_name                       # Use the compute registered
pipeline_run_config.environment = registered_env                # Assign the environment to the run configuration
print ('Run configuration created.')

# Create an OutputFileDatasetConfig (temporary Data Reference) for data passed from step 1 to step 2
prepped_data = OutputFileDatasetConfig('prepped_data')

# Review ./experiments/* which includes example pipeline steps
experiment_folder = './experiments' # Pipeline steps folder

# Step 1, Run the data prep script
prep_step = PythonScriptStep(
    name = 'Prepare Data',                                      # Step name
    source_directory = experiment_folder,                       # Step py file location
    script_name = '06_data_prep.py',                               # Step py file name
    arguments = [                                               # Experiment parameter 
        '--input-data', diabetes_ds.as_named_input('raw_data'), # Reference to tabular dataset
        '--prepped-data', prepped_data                          # Reference to output data
    ],                                                          
    compute_target = cluster_name,                              # Compute target
    runconfig = pipeline_run_config,                            # Pipeline config
    allow_reuse = True                                          # Reuse of previous calculations
)

# Step 2, run the training script
train_step = PythonScriptStep(
    name = 'Train and Register Model',                          # Step name
    source_directory = experiment_folder,                       # Step py file location
    script_name = '06_train_model.py',                             # Step py file name
    arguments = [                                               # Experiment parameter 
        '--training-data', prepped_data.as_input(),             # Reference to step 1 output data
        '--regularization', 0.1                                 # Regularizaton rate parameter
    ],                                                          
    compute_target = cluster_name,                              # Compute target
    runconfig = pipeline_run_config,                            # Pipeline config
    allow_reuse = True                                          # Reuse of previous calculations
)

print('Pipeline steps defined')

# Construct the pipeline
pipeline_steps = [prep_step, train_step]
pipeline = Pipeline(workspace=ws, steps=pipeline_steps)
print('Pipeline is built.')

#-----EXPERIMENT---------------------------------------------------------------#
# Create an Azure ML experiment in workspace
experiment_name = 'ml-sdk-pipeline'
experiment = Experiment(workspace=ws, name=experiment_name)

#-----RUN----------------------------------------------------------------------#
'''
Run object is a reference to an individual run of an experiment in Azure Machine Learning
'''
pipeline_run = experiment.submit(pipeline, regenerate_outputs=True)
print('Pipeline submitted for execution.')

# In Jupyter Notebooks, use RunDetails widget to see a visualization of the run details
# RunDetails(pipeline_run).show()

pipeline_run.wait_for_completion(show_output=True)

#-----TROUBLESHOOT-------------------------------------------------------------#
'''
Troubleshoot the experiment run
* Use get_details method to retrieve basic details about the run
* Use get_details_with_logs method to retrieve run details as well as contents of log files
'''
run_details = pipeline_run.get_details_with_logs()
# print(f'Run details: \n\t{run_details}')

# Download log files
log_folder = 'downloaded-logs'
pipeline_run.get_all_logs(destination=log_folder)
# Verify the files have been downloaded
for root, directories, filenames in os.walk(log_folder): 
    for filename in filenames:  
        print (os.path.join(root,filename))

'''
Download the files produced by the experiment e.g. for logged visualizations
* Either individually by using the download_file method
* Or by using the download_files method to retrieve multiple files
'''
# Download 
download_folder = 'downloaded-files'
# Download files in the 'outputs' folder
pipeline_run.download_files(prefix='outputs', output_directory=download_folder)
# Verify the files have been downloaded
for root, directories, filenames in os.walk(download_folder): 
    for filename in filenames:  
        print (os.path.join(root,filename))

#-----REGISTER_MODEL-----------------------------------------------------------#
'''
Register run machine learning model
* Outputs of the experiment also include the trained model file
* Register model in your Azure Machine Learning workspace
* Allowing to track model versions and retrieve them later
'''
pipeline_run.register_model(
    model_path='outputs/diabetes_model.pkl',
    model_name='diabetes_model',
    tags={'Training context':'Script'},
    properties={
        'AUC': pipeline_run.get_metrics()['AUC'],
        'Accuracy': pipeline_run.get_metrics()['Accuracy']
    }
)

# List registered models
# for model in Model.list(ws):
#     print(model.name, 'version:', model.version)
#     for tag_name in model.tags:
#         tag = model.tags[tag_name]
#         print ('\t',tag_name, ':', tag)
#     for prop_name in model.properties:
#         prop = model.properties[prop_name]
#         print ('\t',prop_name, ':', prop)
#     print('\n')

#-----ENDPOINT-----------------------------------------------------------------#
'''
Endpoint for model training calls
* To use an endpoint, client applications need to make a REST call over HTTP
* Request must be authenticated --> authorization header is required
* Real application would require a service principal with which to be authenticated
* For now, use the authorization header from the current connection to Azure workspace
'''
# Publish the pipeline from the run as a REST service
published_pipeline = pipeline_run.publish_pipeline(
    name='diabetes-training-pipeline', description='Trains diabetes model', version='1.0')

# Find its URI as a property of the published pipeline object
rest_endpoint = published_pipeline.endpoint
print(rest_endpoint)

# Define authentication header
interactive_auth = InteractiveLoginAuthentication()
auth_header = interactive_auth.get_authentication_header()
print('Authentication header ready.')

# Make REST call to get pipeline run ID
rest_endpoint = published_pipeline.endpoint
response = requests.post(
    rest_endpoint, 
    headers=auth_header, 
    json={'ExperimentName': experiment_name}
)
run_id = response.json()['Id']

# Use run ID to wait for pipeline to finish
published_pipeline_run = PipelineRun(ws.experiments[experiment_name], run_id)
published_pipeline_run.wait_for_completion(show_output=True)

#-----SCHEDULE-----------------------------------------------------------------#
# Schedule pipeline e.g. for a weekly run
recurrence = ScheduleRecurrence(                                # Submit the Pipeline every Monday at 00:00 UTC
    frequency='Week',
    interval=1,
    week_days=['Monday'],
    time_of_day='00:00'
)
weekly_schedule = Schedule.create(                              # Schedule Pipeline
    ws, name='weekly-diabetes-training', 
    description='Based on time',
    pipeline_id=published_pipeline.id, 
    experiment_name='mslearn-diabetes-pipeline', 
    recurrence=recurrence
)
print('Pipeline scheduled.')

# List schedules
schedules = Schedule.list(ws)
schedules

# Get details of latest run
pipeline_experiment = ws.experiments.get(experiment_name)
latest_run = list(pipeline_experiment.get_runs())[0]
latest_run.get_details()