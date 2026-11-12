import os
import sys

from tests.new_fixtures import assert_query_does_nothing, holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test__load_xml_does_nothing(holder):
    sql = """
    LOAD XML LOCAL INFILE 'person.xml'
      INTO TABLE person
      ROWS IDENTIFIED BY '<person>';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert_query_does_nothing(h)
