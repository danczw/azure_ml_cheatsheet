# Import libraries
from azureml.core import Workspace
import matplotlib.pyplot as plt
import opendp.smartnoise.core as sn
import pandas as pd

#-----WORKSPACE----------------------------------------------------------------#
# Load workspace from config JSON file
ws = Workspace.from_config()                                    # Returns a workspace object based on config file 
print(ws.name, 'loaded')

#-----DATASET------------------------------------------------------------------#
# Get the training dataset from registered datasets (see ./01_datastores.py)
data = ws.datasets.get('diabetes dataset')                      # Get specified dataset from list of all datasets in workspace

#-----DIFFERENTIAL_PRIVACY-----------------------------------------------------#
'''
Differential privacy
* technique designed to preserve the privacy of individual data points by adding "noise" to the data

opendb-smartnoise
* aims to provide building blocks for using differential privacy in data analysis and machine learning projects
* use SmartNoise to create an analysis in which noise is added to the source data
* Underlying mathematics can be very complex, some concepts to be aware of include:
    * Upper and lower bounds:
        * Clamping is used to set upper and lower bounds on values for a variable
        * Ensure that the noise generated by SmartNoise is consistent with the expected distribution of the original data
    * Sample size:
        * To generate consistent differentially private data for some aggregations, SmartNoise needs to know the size of the data sample to be generated
    * Epsilon:
        * Non-negative value providing an inverse measure of the amount of noise added to the data
        * A low epsilon results in a dataset with a greater level of privacy
        * High epsilon results in a dataset that is closer to the original data
        * Values should be between 0 and 1 generally
        * Correlated with another value delta: indicates the probability that a report generated by an analysis is not fully private
'''
# Creates an analysis and report mean Age value from differentially private data
cols = list(data.columns)
age_range = [0.0, 120.0]
samples = len(data)

with sn.Analysis() as analysis:  
    # Convert Age to float
    age_dt = sn.to_float(data['Age'])
    
    # Get mean of age
    age_mean = sn.dp_mean(
        data = age_dt,
        privacy_usage = {'epsilon': .50},
        data_lower = age_range[0],
        data_upper = age_range[1],
        data_rows = samples
    )
    
analysis.release()

#-----ANALYSIS-----------------------------------------------------------------#
ages = list(range(0, 130, 10))
age = data.Age

# print differentially private estimate of mean age
print("Private mean age:",age_mean.value)

# print actual mean age
print("Actual mean age:",data.Age.mean())

# Compare differentially private histogram of Age to original data
with sn.Analysis() as analysis:
    age_histogram = sn.dp_histogram(
            sn.to_int(data['Age'], lower=0, upper=120),
            edges = ages,
            upper = 10000,
            null_value = -1,
            privacy_usage = {'epsilon': 0.5}
        )
    
analysis.release()

# Plot a histogram with 10-year bins of original data
n_age, bins, patches = plt.hist(age, bins=ages, color='blue', alpha=0.7, rwidth=0.85)
plt.grid(axis='y', alpha=0.75)
plt.xlabel('Age')
plt.ylabel('Frequency')
plt.title('True Age Distribution')
plt.show()

# Plot a histogram with 10-year bins of original data and privatized data
plt.ylim([0,7000])
width=4
agecat_left = [x + width for x in ages]
agecat_right = [x + 2*width for x in ages]
plt.bar(list(range(0,120,10)), n_age, width=width, color='blue', alpha=0.7, label='True')
plt.bar(agecat_left, age_histogram.value, width=width, color='orange', alpha=0.7, label='Private')
plt.legend()
plt.title('Histogram of Age')
plt.xlabel('Age')
plt.ylabel('Frequency')
plt.show()

# Differentially private covariance to establish relationships between variables
with sn.Analysis() as analysis:
    age_bp_cov_scalar = sn.dp_covariance(
                left = sn.to_float(data['Age']),
                right = sn.to_float(data['DiastolicBloodPressure']),
                privacy_usage = {'epsilon': 1.0},
                left_lower = 0.,
                left_upper = 120.,
                left_rows = 10000,
                right_lower = 0.,
                right_upper = 150.,
                right_rows = 10000)
analysis.release()
print('Differentially private covariance: {0}'.format(age_bp_cov_scalar.value[0][0]))
print('Actual covariance', data.Age.cov(data.DiastolicBloodPressure))