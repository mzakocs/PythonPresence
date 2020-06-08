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
        self.port = config['DATABASECONFIG']['port']
        self.user = config['DATABASECONFIG']['user']
        self.password = config['DATABASECONFIG']['password']
        self.database = config['DATABASECONFIG']['database']
        self.table = config['DATABASECONFIG']['table']
        self.readcolumn = config['DATABASECONFIG']['readcolumn'] # The column that has the SIP extensions
        self.writecolumn = config['DATABASECONFIG']['writecolumn'] # The column that will be written to with the updated presence
        # Initiates the database connection
        self.conn = psycopg2.connect(host = self.host, database = self.database, user = self.user, password = self.password, port = self.port)
        # Creates a cursor
        self.cur = self.conn.cursor()
        
    def loadExtensions(self):
        # Executes the query to read all extensions
        query = "SELECT DISTINCT " + self.readcolumn + " FROM " + self.table + " WHERE " + self.readcolumn + " IS NOT NULL"
        self.cur.execute(query)
        # Read the values
        extensionlist = self.cur.fetchall()
        formattedextensionlist = []
        # Convert the values from tuples into their individual values
        for result in extensionlist:
            formattedextensionlist.append(str(result[0]))
        print("Retrieved new Subscribe Extensions from DB: %s" % formattedextensionlist)
        # Add the subscriptions
        self.subscriptionapp._setup_new_subscriptions(formattedextensionlist)

    def updatePresence(self, extension, presence):
        # Executes the query to update the record
        query = "UPDATE " + self.table + " SET " + self.writecolumn + " = '" + str(presence) + "' WHERE " + self.readcolumn + " = '" + str(extension) + "'"
        status = self.cur.execute(query)
        self.conn.commit()

    def destroyDBConnection(self):
        # Close the cursor
        self.cur.close()
        # Closes the connection to the database
        self.conn.close()

        