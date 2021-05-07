## Feature Imputation Configuration Usage Guide.

#### Example Tasks

This section introduces the dsl and conf for different types of tasks.

1. Feature Imputation using Designated Replace Value for All Columns:

    example-data: (1) guest: breast_hetero_guest.csv (2) host: breast_hetero_host.csv  

    dsl: feature_imputation_job_dsl.json

    runtime_config : feature_imputation_designated_conf.json

2. Feature Imputation using the Same Method for All Columns:

    example-data: (1) guest: dvisits_hetero_guest.csv (2) host: dvisists_hetero_host.csv  
    
    dsl: feature_imputation_job_dsl.json

    runtime_config : feature_imputation_method_conf.json

3. Feature Imputation using Different Methods for Different Columns:
    
    example-data: (1) guest: dvisits_hetero_guest.csv (2) host: dvisists_hetero_host.csv  
    
    dsl: feature_imputation_job_dsl.json

    runtime_config : feature_imputation_column_method_conf.json

Users can use following commands to run a task.

    flow job submit -c ${runtime_config} -d ${dsl}

Moreover, after successfully running the training task, you can use it to predict too.
