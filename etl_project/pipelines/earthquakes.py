# Enviornment Imports
from dotenv import load_dotenv
import os
from sqlalchemy import Table, MetaData, Column, NUMERIC, String, Float, TIMESTAMP, DECIMAL
import yaml
from pathlib import Path
import  time
import schedule

# Project Imports
from etl_project.connectors.earthquakes import EarthquakesApiClient
from etl_project.connectors.postgresql import PostgreSqlClient
from etl_project.assets.pipeline_logging import PipelineLogging
from etl_project.assets.metadata_logging import MetaDataLogging, MetaDataLoggingStatus 
from etl_project.assets.earthquakes import (
    extract_earthquakes_data,
    transform,
    load
)

def run_pipeline(
    pipeline_name: str,
    postgresql_logging_client: PostgreSqlClient,
    pipeline_config: dict,
):
    pipeline_logging = PipelineLogging(
        pipeline_name=pipeline_name,
        log_folder_path=pipeline_config.get("config").get("log_folder_path"),
    )
    metadata_logger = MetaDataLogging(
        pipeline_name=pipeline_name,
        postgresql_client=postgresql_logging_client,
        config=pipeline_config.get("config"),
    )
    try:
        metadata_logger.log()  # log start
        pipeline(
            config=pipeline_config.get("config"), pipeline_logging=pipeline_logging
        )
        metadata_logger.log(
            status=MetaDataLoggingStatus.RUN_SUCCESS, logs=pipeline_logging.get_logs()
        )  # log end
        pipeline_logging.logger.handlers.clear()
    except BaseException as e:
        pipeline_logging.logger.error(f"Pipeline run failed. See detailed logs: {e}")
        metadata_logger.log(
            status=MetaDataLoggingStatus.RUN_FAILURE, logs=pipeline_logging.get_logs()
        )  # log error
        pipeline_logging.logger.handlers.clear()



def pipeline(config: dict, pipeline_logging: PipelineLogging):
    pipeline_logging.logger.info("Starting pipeline run")
    # set up enviormental variables
    pipeline_logging.logger.info("Getting ENV variables")
    SERVER_NAME = os.environ.get("SERVER_NAME")
    DATABASE_NAME = os.environ.get("DATABASE_NAME")
    DB_USERNAME = os.environ.get("DB_USERNAME")
    DB_PASSWORD = os.environ.get("DB_PASSWORD")
    PORT = os.environ.get("PORT")
    # set up config fact variables
    base_url = config.get("base_url")
    method = config.get("method")

    # Make Earthquake Client
    pipeline_logging.logger.info("Creating Earthquake API client")
    earthquakes_client = EarthquakesApiClient(base_url=base_url, method=method )

    # Extract
    pipeline_logging.logger.info("Extracting data from Earthquake API")
    df_earthquakes = extract_earthquakes_data(
        earthquakes_client=earthquakes_client,
        start_time=config.get("start_time"),
        end_time = config.get("end_time"),
        layer_name=config.get("layer_name")
    )
    # print(df_earthquakes.head())

    # transform
    pipeline_logging.logger.info("Transform dataframes")
    df_transformed_table_1 = transform(
        df=df_earthquakes,
        selection_list=
        ["type", 
         "id", 
         "properties.place", 
         "properties.title",
         "properties.time",
         "properties.updated",
         "properties.nst",
         "properties.dmin",
         "properties.rms",
        #  "properties.mag",

        #  "properties.gap",
        #  "properties.magType",
        #  "geometry.coordinates"
         ]
    )

    df_transformed_table_2 = transform(
        df=df_earthquakes,
        selection_list=
        [
         "id",
         "properties.mag",
         "properties.gap",
         "properties.magType",
         "geometry.coordinates"
         ]
    )
    # print(df_transformed.head())

    # load
    pipeline_logging.logger.info("Loading data to postgres")
    postgresql_client = PostgreSqlClient(
        server_name=SERVER_NAME,
        database_name=DATABASE_NAME,
        username=DB_USERNAME,
        password=DB_PASSWORD,
        port=PORT,
    )
    metadata = MetaData()
    table = Table(
        f"table_{config.get('table_name')}_data",
        metadata,
        Column("type", String),
        Column("id", String, primary_key=True),
        Column("properties.place", String),
        Column("properties.title", String),
        Column("properties.time", TIMESTAMP),
        Column("properties.updated", TIMESTAMP),
        Column("properties.nst", String(500)),
        Column("properties.dmin", String(500)),
        Column("properties.rms", String(500)),

        # Column("properties.gap", NUMERIC),
        # Column("properties.magType", String),
        # Column("geometry.coordinates", String)



    )

    table2 = Table(
        f"table_{config.get('table_name')}_2_data",
        metadata,
        Column("id", String, primary_key=True),
        Column("properties.mag", String(500)),
        Column("properties.gap", NUMERIC),
        Column("properties.magType", String),
        Column("geometry.coordinates", String)



    )
    load(
        df=df_transformed_table_1,
        postgresql_client=postgresql_client,
        table=table,
        metadata=metadata,
        load_method="upsert"
    )
    pipeline_logging.logger.info("Pipeline run successful Table 1")

    load(
        df=df_transformed_table_2,
        postgresql_client=postgresql_client,
        table=table2,
        metadata=metadata,
        load_method="upsert"
    )
    pipeline_logging.logger.info("Pipeline run successful Table 2")


if __name__ == "__main__":
    load_dotenv()
    LOGGING_SERVER_NAME = os.environ.get("LOGGING_SERVER_NAME")
    LOGGING_DATABASE_NAME = os.environ.get("LOGGING_DATABASE_NAME")
    LOGGING_USERNAME = os.environ.get("LOGGING_USERNAME")
    LOGGING_PASSWORD = os.environ.get("LOGGING_PASSWORD")
    LOGGING_PORT = os.environ.get("LOGGING_PORT")

    postgresql_logging_client = PostgreSqlClient(
    server_name=LOGGING_SERVER_NAME,
    database_name=LOGGING_DATABASE_NAME,
    username=LOGGING_USERNAME,
    password=LOGGING_PASSWORD,
    port=LOGGING_PORT,
)
    # get config variables
    yaml_file_path = __file__.replace(".py", ".yaml")
    if Path(yaml_file_path).exists():
        with open(yaml_file_path) as yaml_file:
            pipeline_config = yaml.safe_load(yaml_file)
            PIPELINE_NAME = pipeline_config.get("name")
    else:
        raise Exception(
            f"Missing {yaml_file_path} file! Please create the yaml file with at least a `name` key for the pipeline name."
        )

    # set schedule
    schedule.every(pipeline_config.get("schedule").get("run_seconds")).seconds.do(
        run_pipeline,
        pipeline_name=PIPELINE_NAME,
        postgresql_logging_client=postgresql_logging_client,
        pipeline_config=pipeline_config,
    )

    while True:
        schedule.run_pending()
        time.sleep(pipeline_config.get("schedule").get("poll_seconds"))

    
    
