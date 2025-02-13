from collections import OrderedDict
from typing import Optional
from mindsdb_sql.parser.ast.base import ASTNode
from mindsdb.integrations.libs.base import DatabaseHandler
from mindsdb.utilities import log
from mindsdb_sql import parse_sql
from mindsdb.integrations.libs.response import (
    HandlerStatusResponse as StatusResponse,
    HandlerResponse as Response,
    RESPONSE_TYPE
)
from mindsdb.integrations.libs.const import HANDLER_CONNECTION_ARG_TYPE as ARG_TYPE
import pandas as pd
import jaydebeapi as jdbcconnector


class NuoHandler(DatabaseHandler):


    name= 'nuo_jdbc'


    def __init__(self, name: str, connection_data: Optional[dict], **kwargs):
        """ Initialize the handler
        Args:
            name (str): name of particular handler instance
            connection_data (dict): parameters for connecting to the database
            **kwargs: arbitrary keyword arguments.
        """
        super().__init__(name)
        
        self.kwargs = kwargs
        self.parser = parse_sql
        self.database = connection_data['database']
        self.connection_config = connection_data
        self.host = connection_data['host']
        self.port = connection_data['port']
        self.user = connection_data['user']
        self.is_direct = connection_data['is_direct']
        self.password = connection_data['password']
        self.connection = None
        self.is_connected = False
        self.schema = None

        self.jdbc_url = self.construct_jdbc_url()
    
    def connect(self):
        """ Set up any connections required by the handler
        Should return output of check_connection() method after attempting
        connection. Should switch self.is_connected.
        Returns:
            Connection Object
        """
        if self.is_connected is True:
            return self.connection

        jdbc_class = "com.nuodb.jdbc.Driver"
        jar_location = self.connection_config.get('jar_location')

        try: 
            if(jar_location): 
                self.connection = jdbcconnector.connect(jclassname=jdbc_class, url=self.jdbc_url, jars=jar_location)
            else: 
                self.connection = jdbcconnector.connect(jclassname=jdbc_class, url=self.jdbc_url)
        except Exception as e:
            log.logger.error(f"Error while connecting to {self.database}, {e}")

        return self.connection

    def construct_jdbc_url(self):
        """ Constructs the JDBC url based on the paramters provided to the handler class.\
        Returns: 
            The JDBC connection url string. 
        """

        jdbc_url = "jdbc:com.nuodb://" + self.host

        if port := self.connection_config.get('port'):
            jdbc_url = jdbc_url + ":" + str(port)

        jdbc_url = jdbc_url + "/" + self.database + "?user=" + self.user + "&password=" + self.password 

        if schema := self.connection_config.get('schema'):
            self.schema = schema
            jdbc_url = jdbc_url + "&schema=" + schema

        #sets direct paramter only if the paramters is specified to be true
        if(str(self.is_direct).lower() == 'true'): 
            jdbc_url = jdbc_url + "&direct=true"


        if driver_args := self.connection_config.get('driver_args'):
            driver_arg_string = '&'.join(driver_args.split(","))
            jdbc_url = jdbc_url + "&" + driver_arg_string 

        return jdbc_url 
        

    def disconnect(self):
        """ Close any existing connections
        Should switch self.is_connected.
        """
        if self.is_connected is False:
            return
        try:
            self.connection.close()
            self.is_connected=False
        except Exception as e:
            log.logger.error(f"Error while disconnecting to {self.database}, {e}")

        return 


    def check_connection(self) -> StatusResponse:
        """ Check connection to the handler
        Returns:
            HandlerStatusResponse
        """
        responseCode = StatusResponse(False)
        need_to_close = self.is_connected is False

        try:
            self.connect()
            responseCode.success = True
        except Exception as e:
            log.logger.error(f'Error connecting to database {self.database}, {e}!')
            responseCode.error_message = str(e)
        finally:
            if responseCode.success and need_to_close:
                self.disconnect()
            if not responseCode.success and self.is_connected is True:
                self.is_connected = False

        return responseCode


    def native_query(self, query: str) -> StatusResponse:
        """Receive raw query and act upon it somehow.
        Args:
            query (Any): query in native format (str for sql databases,
                dict for mongo, etc)
        Returns:
            HandlerResponse
        """
        need_to_close = self.is_connected is False
        conn = self.connect()
        with conn.cursor() as cur:
            try:
                cur.execute(query)
                if cur.description:
                    result = cur.fetchall() 
                    response = Response(
                        RESPONSE_TYPE.TABLE,
                        data_frame=pd.DataFrame(
                            result,
                            columns=[x[0] for x in cur.description]
                        )
                    )
                else:
                    response = Response(RESPONSE_TYPE.OK)
                self.connection.commit()
            except Exception as e:
                log.logger.error(f'Error running query: {query} on {self.database}!')
                response = Response(
                    RESPONSE_TYPE.ERROR,
                    error_message=str(e)
                )
                self.connection.rollback()

        if need_to_close:
            self.disconnect()

        return response

    
    def query(self, query: ASTNode) -> StatusResponse:
        """Render and execute a SQL query.

        Args:
            query (ASTNode): The SQL query.

        Returns:
            Response: The query result.
        """
        query_str = query.to_string() if isinstance(query, ASTNode) else str(query)
        return self.native_query(query_str)


    def get_tables(self) -> StatusResponse:
        """Get a list of all the tables in the database.

        Returns:
            Response: Names of the tables in the database.
        """
        if self.schema: 
            query = f''' SELECT TABLENAME FROM SYSTEM.TABLES WHERE SCHEMA = '{self.schema}' '''
        else: 
            query = ''' SELECT TABLENAME FROM SYSTEM.TABLES WHERE SCHEMA != 'SYSTEM' '''
    
        result = self.native_query(query)
        df = result.data_frame
        result.data_frame = df.rename(columns={df.columns[0]: 'table_name'})
        return result

    
    def get_columns(self, table_name: str) -> StatusResponse:
        """Get details about a table.

        Args:
            table_name (str): Name of the table to retrieve details of.

        Returns:
            Response: Details of the table.
        """

        query = f''' SELECT FIELD FROM SYSTEM.FIELDS WHERE TABLENAME='{table_name}' '''
        return self.native_query(query)
    
    
connection_args = OrderedDict(
    host={
        'type': ARG_TYPE.STR,
        'description': 'The host name or IP address of the NuoDB AP or TE. If is_direct is set to true then provide the TE IP else provide the AP IP.'
    },
    port={
        'type': ARG_TYPE.INT,
        'description': 'Specify port to connect to NuoDB. If is_direct is set to true then provide the TE port else provide the AP port.'
    },
    database={
        'type': ARG_TYPE.STR,
        'description': """
            The database name to use when connecting with the NuoDB.
        """
    },
    schema={
        'type': ARG_TYPE.STR,
        'description': """
            The schema name to use when connecting with the NuoDB.
        """
    },
    user={
        'type': ARG_TYPE.STR,
        'description': 'The username to authenticate with the NuoDB server.'
    },
    password={
        'type': ARG_TYPE.STR,
        'description': 'The password to authenticate the user with the NuoDB server.'
    },
    is_direct={
        'type': ARG_TYPE.STR,
        'description': 'This argument indicates whether a direct connection to the TE is to be attempted.'
    },
    jar_location={
        'type': ARG_TYPE.STR,
        'description': 'The location of the jar files which contain the JDBC class. This need not be specified if the required classes are already added to the CLASSPATH variable.'
    },
    driver_args={
        'type': ARG_TYPE.STR,
        'description': """
            The extra arguments which can be specified to the driver. 
            Specify this in the format: "arg1=value1,arg2=value2. 
            More information on the supported paramters can be found at: https://doc.nuodb.com/nuodb/latest/deployment-models/physical-or-vmware-environments-with-nuodb-admin/reference-information/connection-properties/'
        """
    }
)


connection_args_example = OrderedDict(
    host="localhost",
    port="48006",
    database="test",
    schema="hockey",
    user="dba",
    password="goalie",
    jar_location="/Users/kavelbaruah/Desktop/nuodb-jdbc-24.0.0.jar",
    is_direct="true",
    driver_args="schema=hockey,clientInfo=info"
)

