import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


def test__user_defined_function_lambda(holder):
    sql = """
    USING EXTERNAL FUNCTION my_udf(name VARCHAR)
    RETURNS VARCHAR
    LAMBDA 'my_lambda_function'
    SELECT my_udf(expression) FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert len(h.collected_queries.unsupported) == 1


def test__user_defined_function_sagemaker(holder):
    sql = """
    USING EXTERNAL FUNCTION predict_customer_registration(age INTEGER)
        RETURNS DOUBLE
        SAGEMAKER 'xgboost-2019-09-20-04-49-29-303'
    SELECT predict_customer_registration(age) AS probability_of_enrolling, customer_id
         FROM "sampledb"."ml_test_dataset"
         WHERE predict_customer_registration(age) < 0.5;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert len(h.collected_queries.unsupported) == 1
