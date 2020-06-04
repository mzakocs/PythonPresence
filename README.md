# PythonPresence  
> SIP Backend for BLF and WebPresence through JSON based SIP commands written in Python 2.7  

## Notes  
- The database helper class currently only supports PostgreSQL. This can be very easily changed to any flavor of SQL you like. 
- The updates for WebPresence and BLF are sent out over SIP messaging to a command extension. 
You need to write something on your front end to parse these JSON requests and act on them accordingly.  
- The app is written in Python 2.7 because of compatibility reasons with SIPSIMPLE, the SIP stack library used in this application.  
- You need to add an account with SIPSIMPLE in your favorite terminal emulator before you can run the app. For Example:
> sip-settings -a add user@domain password  

## Dependencies  
Install these dependencies for the app to work correctly

> pip install configparser    

> pip install psycopg2    

> pip install python-sipsimple    


These dependencies are for config files, postgres support, and SIP stack support respectively.
