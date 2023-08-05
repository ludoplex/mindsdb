from mindsdb.api.mysql.mysql_proxy.datahub.datanodes import InformationSchemaDataNode


def init_datahub(session):
    return InformationSchemaDataNode(session)
