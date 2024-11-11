from airflow import DAG
from airflow.models import Variable
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.decorators import task

from datetime import datetime
from datetime import timedelta

import requests
import logging

def get_Redshift_connection(autocommit=True):
    hook = PostgresHook(postgres_conn_id='redshift_dev_db')
    conn = hook.get_conn()
    conn.autocommit = autocommit
    return conn.cursor()

@task
def extract(url):
    response = requests.get('url')
    countries = response.json()
    records = []

    for country in countries:
        name = country['name']['common']
        population = country['population']
        area = country['area']
        records.append([name, population, area])
    return records

def _create_table(cur, schema, table, drop_first):
    if drop_first:
        cur.execute(f"DROP TABLE IF EXISTS {schema}.{table};")
    cur.execute(f"""
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    name varchar(32),
    population int,
    area float
);""")

@task
def load(schema, table, records):
    logging.info("load started")
    cur = get_Redshift_connection()
    try:
        cur.execute("BEGIN;")
        # 원본 테이블이 없으면 생성 - 테이블이 처음 만들어질 때 
        _create_table(cur, schema, table, False)
        # 임시 테이블로 원본 테이블 복사
        cur.execute(f"CREATE TEMP TABLE t AS SELECT * FROM {schema}.{table};")
        for r in records:
            sql = f"INSERT INTO t VALUES ('{r[0]}', {r[1]}, {r[2]});"
            print(sql)
            cur.execute(sql)

        # 원본 테이블 생성
        _create_table(cur, schema, table, True)
        # 임시 테이블 내용을 원본 테이블로 복사해오기(중복 제거)
        cur.execute(f"INSERT INTO {schema}.{table} SELECT DISTINCT * FROM t;")
        cur.execute("COMMIT")
    except Exception as error:
        print(error)
        cur.execute("ROLLBACK")
        raise
    logging.info("load one")

with DAG(
    dag_id = 'GetCountryInfo',
    start_date = datetime(2024,11,9),
    schedule='30 6 * * 6',
    max_active_runs=1,
    catchup=False,
    default_args={
        'retries': 1,
        'retry_delay': timedelta(minutes=3),
        # 'on_failure_callback': slack.on_failure_callback,
    }    
) as dag:

    url = Variable.get("country_csv_url")
    schema = 'ba00729'   ## 자신의 스키마로 변경
    table = 'countryinfo'

    result = extract(url)
    load(schema, table, result)
