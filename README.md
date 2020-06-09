# PythonPresence  
> SIP Backend for BLF and WebPresence through PostgreSQL and JSON based SIP commands written in Python 2.7  
<p align="center"><img width="350" height="90" src="media/ring.gif"></p>

## Purpose
SIP, or Session Initiation Protocol, allows you to maintain voice and video calls through a system of sessions. Within SIP there are features known as Presence and Busy Lamp Field, which allow you to see when other users are on a phone call, dialing somebody else, hanging up and more.  

While trying to implement a phone that uses SIP using SIP.js, a javascript based SIP stack, I discovered a very unfortunate problem. Due to limitations of WSS (a secure websocket used to transmit SIP voice and video data for web browsers), this feature is not functional on any Javascript/Web-based phones.  

In order to combat this flaw, this Python service uses UDP instead of WSS to communicate with the SIP server as a workaround. Its sole purpose is to create subscriptions, listen for notifications and updates on the status of other users, and process these notifications into a readable format which can be put into a database for easy access by any web-based SIP application.

## Notes  
- You need a valid SIP switch to connect to in order to use this. I personally reccomend [FreeSWITCH by Signalwire](https://freeswitch.com/) and [FusionPBX](https://github.com/fusionpbx/fusionpbx), as this app was developed for and tested with this setup. The server should be compatible with most modern SIP switches, but it is not guaranteed and may vary from setup to setup.
- A SIP message is sent out to a COMMAND extension to notify everybody that the database was updated.
Write something in your SIP client to parse these JSON requests and act on them accordingly. Otherwise, you can turn this off easily in the configuration file. 
- The database helper class currently only supports PostgreSQL. This can be very easily changed to any flavor of SQL you like using the multitude of libraries available. If you implement support for another flavor of SQL, please create a pull request and I'll consider merging it.
- You need to add an account with SIPSIMPLE in your favorite terminal emulator before you can run the app.
  > sip-settings -a add user@domain password  

## Dependencies   
To start, add the signing key and repo for SIPSIMPLE that corresponds with your OS here: 

  > https://docs-new.sipthor.net/w/debian_package_repositories/  
  
Afterwards, run these commands in your favorite terminal emulator to install the dependencies.
The package manageres apt and pip are required. 

> sudo apt install python-dev 

> pip install configparser    

> pip install psycopg2    

> sudo apt-get install sipclients  

> sudo apt install python-sipsimple  


These dependencies are for python dev tools, config files, postgres support, SIP configuration and SIP stack support respectively.
