import psycopg2
import configparser

# Manages the config file and pulls info from a DB for SIP extensions to pull from
class DatabaseManager:

    def __init__(self, SubscriptionApp):
        # Imports
        self.subscriptionapp = SubscriptionApp
        # Loads the config file
        config = configparser.ConfigParser()
        try:
            config.read('config.ini')
        except Exception as e:
            print("ERROR: " + e)
            return
        # Loads the values into variables
        self.host = config['DATABASECONFIG']['host']
        self.user = config['DATABASECONFIG']['user']
        self.password = config['DATABASECONFIG']['password']
        self.database = config['DATABASECONFIG']['database']
        self.table = config['DATABASECONFIG']['table']
        self.column = config['DATABASECONFIG']['column']
        # Initiates the database connection
        self.conn = psycopg2.connect(host = self.host, database = self.database, user = self.user, password = self.password)
        
    def loadExtensions(self):
        # Creates a cursor 
        cur = self.conn.cursor()
        # Executes the query to read all extensions
        query = "SELECT DISTINCT " + self.column + " FROM " + self.table + " WHERE " + self.column + " IS NOT NULL"
        cur.execute(query)
        # Read the values
        extensionlist = cur.fetchall()
        formattedextensionlist = []
        # Convert the values from tuples into their individual values
        for result in extensionlist:
            formattedextensionlist.append(str(result[0]))
        print("Retrieved new Subscribe Extensions from DB: %s" % formattedextensionlist)
        # Close the cursor
        cur.close()
        # Add the subscriptions
        self.subscriptionapp._setup_new_subscriptions(formattedextensionlist)

    def destroyDBConnection(self):
        # Closes the connection to the database
        self.conn.close()

        