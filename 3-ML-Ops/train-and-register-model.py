from azureml.pipeline.core.graph import PipelineParameter
from azureml.pipeline.steps import PythonScriptStep
from azureml.pipeline.core import Pipeline
from azureml.core.runconfig import RunConfiguration, CondaDependencies
from azureml.core import Dataset, Datastore
# from azureml.train.dnn import TensorFlow
import os
import sys
from dotenv import load_dotenv
sys.path.insert(1, os.path.abspath("./3-ML-Ops/util"))  # NOQA: E402
from workspace import get_workspace
from attach_compute import get_compute
from attach_aks import get_aks


def main():
    load_dotenv()
    workspace_name = os.environ.get("WS_NAME")
    resource_group = os.environ.get("RG_NAME")
    subscription_id = os.environ.get("SUBSCRIPTION_ID")
    tenant_id = os.environ.get("TENANT_ID")
    app_id = os.environ.get("SP_APP_ID")
    app_secret = os.environ.get("SP_APP_SECRET")
    sources_directory_train = os.environ.get("SOURCES_DIR_TRAIN")
    train_script_path = os.environ.get("TRAIN_SCRIPT_PATH")
    evaluate_script_path = os.environ.get("EVALUATE_SCRIPT_PATH")
    vm_size = os.environ.get("AML_COMPUTE_CLUSTER_SKU")
    compute_name = os.environ.get("AML_COMPUTE_CLUSTER_NAME")
    aks_name = os.environ.get("AKS_CLUSTER_NAME")
    model_name = os.environ.get("MODEL_NAME")
    build_id = os.environ.get("BUILD_BUILDID")
    pipeline_name = os.environ.get("TRAINING_PIPELINE_NAME")
    experiment_name = os.environ.get("EXPERIMENT_NAME")

    # Get Azure machine learning workspace
    aml_workspace = get_workspace(
        workspace_name,
        resource_group,
        subscription_id,
        tenant_id,
        app_id,
        app_secret)

    print('Now accessing:')
    print(aml_workspace)

    # Get Azure machine learning cluster
    aml_compute = get_compute(
        aml_workspace,
        compute_name,
        vm_size)
    if aml_compute is not None:
        print(aml_compute)

    run_config = RunConfiguration(conda_dependencies=CondaDependencies.create(
        conda_packages=['numpy', 'pandas',
                        'scikit-learn', 'keras'],
        pip_packages=['azureml-core==1.25.0',
                      'azureml-defaults==1.25.0',
                      'azureml-telemetry==1.25.0',
                      'azureml-train-restclients-hyperdrive==1.25.0',
                      'azureml-train-core==1.25.0',
                      'azureml-dataprep',
                      'tensorflow-gpu==2.0.0',
                      'transformers==2.0.0',
                      'absl-py',
                      'azureml-dataprep',
                      'h5py<3.0.0'])
    )
    # run_config.environment.docker.enabled = True

    datastore_name = 'mtcseattle'
    container_name = 'azure-service-classifier'
    account_name = 'mtcseattle'
    sas_token = '?sv=2020-04-08&st=2021-05-26T04%3A39%3A46Z&se=2022-05-27T04%3A39%3A00Z&sr=c&sp=rl&sig=CTFMEu24bo2X06G%2B%2F2aKiiPZBzvlWHELe15rNFqULUk%3D'

    try:
        existing_datastore = Datastore.get(aml_workspace, datastore_name)
    except:  # noqa: E722
        existing_datastore = Datastore \
            .register_azure_blob_container(workspace=aml_workspace,
                                           datastore_name=datastore_name,
                                           container_name=container_name,
                                           account_name=account_name,
                                           sas_token=sas_token,
                                           overwrite=True)

    azure_dataset = Dataset.File.from_files(
        path=(existing_datastore, 'data'))

    azure_dataset = azure_dataset.register(
        workspace=aml_workspace,
        name='Azure Services Dataset',
        description='Dataset containing azure related posts on Stackoverflow',
        create_new_version=True)

    azure_dataset.to_path()
    input_data = azure_dataset.as_named_input('azureservicedata').as_mount(
        '/tmp/data')

    model_name = PipelineParameter(
        name="model_name", default_value=model_name)
    max_seq_length = PipelineParameter(
        name="max_seq_length", default_value=128)
    learning_rate = PipelineParameter(
        name="learning_rate", default_value=3e-5)
    num_epochs = PipelineParameter(
        name="num_epochs", default_value=1)
    export_dir = PipelineParameter(
        name="export_dir", default_value="./outputs/exports")
    batch_size = PipelineParameter(
        name="batch_size", default_value=32)
    steps_per_epoch = PipelineParameter(
        name="steps_per_epoch", default_value=1)

    # initialize the PythonScriptStep
    train_step = PythonScriptStep(
        name='Train Model',
        script_name=train_script_path,
        arguments=['--data_dir', input_data,
                   '--max_seq_length', max_seq_length,
                   '--batch_size', batch_size,
                   '--learning_rate', learning_rate,
                   '--steps_per_epoch', steps_per_epoch,
                   '--num_epochs', num_epochs,
                   '--export_dir',export_dir],
        compute_target=aml_compute,
        source_directory=sources_directory_train,
        runconfig=run_config,
        allow_reuse=True)
    print("Step Train created")

    evaluate_step = PythonScriptStep(
        name="Evaluate Model ",
        script_name=evaluate_script_path,
        compute_target=aml_compute,
        source_directory=sources_directory_train,
        arguments=[
            "--model_name", model_name,
            "--build_id", build_id,
        ],
        runconfig=run_config,
        allow_reuse=False,
    )
    print("Step Evaluate created")

    # Currently, the Evaluate step will automatically register
    # the model if it performs better. This step is based on a
    # previous version of the repo which utilized JSON files to
    # track evaluation results.

    evaluate_step.run_after(train_step)
    steps = [evaluate_step]

    train_pipeline = Pipeline(workspace=aml_workspace, steps=steps)
    train_pipeline.validate()
    published_pipeline = train_pipeline.publish(
        name=pipeline_name,
        description="Model training/retraining pipeline.",
        version=build_id
    )
    print(f'Published pipeline: {published_pipeline.name}')
    print(f'for build {published_pipeline.version}')

    response = published_pipeline.submit(  # noqa: F841
               workspace=aml_workspace,
               experiment_name=experiment_name)

    # # Get AKS cluster for deployment
    # aks_compute = get_aks(
    #     aml_workspace,
    #     aks_name
    # )
    # if aks_compute is not None:
    #     print(aks_compute)


if __name__ == '__main__':
    main()
