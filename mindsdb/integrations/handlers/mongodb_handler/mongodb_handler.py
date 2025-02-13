import re
from collections import OrderedDict

from bson import ObjectId
import certifi
import pandas as pd
from pymongo import MongoClient

from mindsdb_sql.parser.ast.base import ASTNode

from mindsdb.utilities import log
from mindsdb.integrations.libs.base import DatabaseHandler
from mindsdb.integrations.libs.const import HANDLER_CONNECTION_ARG_TYPE as ARG_TYPE
from mindsdb.integrations.libs.response import (
    HandlerStatusResponse as StatusResponse,
    HandlerResponse as Response,
    RESPONSE_TYPE
)
from .utils.mongodb_render import MongodbRender
from mindsdb.api.mongo.utilities.mongodb_query import MongoQuery
from mindsdb.api.mongo.utilities.mongodb_parser import MongodbParser

class MongoDBHandler(DatabaseHandler):
    """
    This handler handles connection and execution of the MongoDB statements.
    """

    name = 'mongodb'

    def __init__(self, name, **kwargs):
        super().__init__(name)
        connection_data = kwargs['connection_data']
        self.host = connection_data.get("host")
        self.port = int(connection_data.get("port") or 27017)
        self.user = connection_data.get("username")
        self.password = connection_data.get("password")
        self.database = connection_data.get('database')
        self.flatten_level = connection_data.get('flatten_level', 0)

        self.connection = None
        self.is_connected = False

    def __del__(self):
        if self.is_connected is True:
            self.disconnect()

    def connect(self):
        kwargs = {}
        if isinstance(self.user, str) and len(self.user) > 0:
            kwargs['username'] = self.user

        if isinstance(self.password, str) and len(self.password) > 0:
            kwargs['password'] = self.password

        if re.match(r'/?.*tls=true', self.host.lower()):
            kwargs['tls'] = True

        if re.match(r'/?.*tls=false', self.host.lower()):
            kwargs['tls'] = False

        if re.match(r'.*.mongodb.net', self.host.lower()) and kwargs.get('tls', None) is None:
            kwargs['tlsCAFile'] = certifi.where()
            if kwargs.get('tls', None) is None:
                kwargs['tls'] = True

        connection = MongoClient(
            self.host,
            port=self.port,
            serverSelectionTimeoutMS=5000,
            **kwargs
        )
        self.is_connected = True
        self.connection = connection
        return self.connection

    def disconnect(self):
        if self.is_connected is False:
            return
        self.connection.close()
        return

    def check_connection(self) -> StatusResponse:
        """
        Check the connection of the database
        :return: success status and error message if error occurs
        """

        result = StatusResponse(False)
        need_to_close = self.is_connected is False

        try:
            con = self.connect()
            con.server_info()
            result.success = True
        except Exception as e:
            log.logger.error(f'Error connecting to MongoDB {self.database}, {e}!')
            result.error_message = str(e)

        if result.success and need_to_close:
            self.disconnect()
        if not result.success and self.is_connected is True:
            self.is_connected = False

        return result

    def native_query(self, query: [str, MongoQuery, dict]) -> Response:

        """
        input str or MongoQuery

        returns the records from the current recordset
        """
        if isinstance(query, str):
            query = MongodbParser().from_string(query)

        if isinstance(query, dict):
            # failback for previous api

            mquery = MongoQuery(query['collection'])

            for c in  query['call']:
                mquery.add_step({
                    'method': c['method'],
                    'args': c['args']
                })

            query = mquery

        collection = query.collection
        database = self.database

        con = self.connect()

        try:

            cursor = con[database][collection]

            for step in query.pipeline:
                fnc = getattr(cursor, step['method'])
                cursor = fnc(*step['args'])

            if result := [
                self.flatten(row, level=self.flatten_level) for row in cursor
            ]:
                df = pd.DataFrame(result)
            else:
                columns = list(self.get_columns(collection).data_frame.Field)
                df = pd.DataFrame([], columns=columns)

            response = Response(
                RESPONSE_TYPE.TABLE,
                df
            )

        except Exception as e:
            log.logger.error(f'Error running query: {query} on {self.database}.{collection}!')
            response = Response(
                RESPONSE_TYPE.ERROR,
                error_message=str(e)
            )

        return response

    def flatten(self, row, level=0):
        # move sub-keys to upper level

        add = {}
        del_keys = []
        edit_keys = {}
        for k, v in row.items():
            # convert objectId to string
            if isinstance(v, ObjectId):
                edit_keys[k] = str(v)
            if level > 0:
                if isinstance(v, dict):
                    for k2, v2 in self.flatten(v, level=level - 1).items():
                        add[f'{k}.{k2}'] = v2
                    del_keys.append(k)
        if add:
            row.update(add)
        for key in del_keys:
            del row[key]
        if edit_keys:
            row.update(edit_keys)

        return row

    def query(self, query: ASTNode) -> Response:
        """
        Retrieve the data from the SQL statement.
        """
        renderer = MongodbRender()
        mquery = renderer.to_mongo_query(query)
        return self.native_query(mquery)

    def get_tables(self) -> Response:
        """
        Get a list with of collection in database
        """
        con = self.connect()
        collections = con[self.database].list_collection_names()
        collections_ar = [
            [i] for i in collections
        ]
        df = pd.DataFrame(collections_ar, columns=['table_name'])

        return Response(RESPONSE_TYPE.TABLE, df)

    def get_columns(self, collection) -> Response:
        """
        Use first row to detect columns
        """
        con = self.connect()
        record = con[self.database][collection].find_one()

        data = []
        if record is not None:
            record = self.flatten(record)

            data.extend([k, type(v).__name__] for k, v in record.items())
        df = pd.DataFrame(data, columns=['Field', 'Type'])

        return Response(RESPONSE_TYPE.TABLE, df)

connection_args = OrderedDict(
    user={
        'type': ARG_TYPE.STR,
        'description': 'The user name used to authenticate with the MongoDB server.',
        'required': True,
        'label': 'User'
    },
    password={
        'type': ARG_TYPE.PWD,
        'description': 'The password to authenticate the user with the MongoDB server.',
        'required': True,
        'label': 'Password'
    },
    database={
        'type': ARG_TYPE.STR,
        'description': 'The database name to use when connecting with the MongoDB server.',
        'required': True,
        'label': 'Database'
    },
    host={
        'type': ARG_TYPE.STR,
        'description': 'The host name or IP address of the MongoDB server. NOTE: use \'127.0.0.1\' instead of \'localhost\' to connect to local server.',
        'required': True,
        'label': 'Host'
    },
    port={
        'type': ARG_TYPE.INT,
        'description': 'The TCP/IP port of the MongoDB server. Must be an integer.',
        'required': True,
        'label': 'Port'
    },
)

connection_args_example = OrderedDict(
    host='127.0.0.1',
    port=27017,
    username='mongo',
    password='password',
    database='database'
)
