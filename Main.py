# Some needed libraries
import sys
import pprint

# The spotify wrapper to request the API
import spotipy.util as util
import spotipy

# The config for the Spotfiy API and for the DB
import config

# The functions necessary to read the RFID tag
from mfrc522 import SimpleMFRC522
import RPi.GPIO as GPIO

# Handles the link with the DB holding the spotify song/album/artist ID
import sqlite3

def authenticateSpotify():
	#----- The app authentication
	CLIENT_ID =  config.CLIENT_ID
	CLIENT_SECRET = config.CLIENT_SECRET
	USERNAME = config.USERNAME
	scope = config.scope


	self.token = util.prompt_for_user_token(USERNAME, scope, client_id=CLIENT_ID, \
	client_secret=CLIENT_SECRET, redirect_uri='http://localhost:8888/callback/')

	if token:
	    sp = spotipy.Spotify(auth=token)
	else:
	    print("Authenticating to Spotify failed. \nCan't get token for {}, \
	    	check your credentials.".format(USERNAME))
	    sys.exit(-1)

	return sp

def connectDatabase(DBFilename):
	conn = sqlite3.connect(DBFilename)
	cursor = conn.cursor()

	#Creating the DB if it doesnt exist
	cursor.execute("""
		CREATE TABLE IF NOT EXISTS RFIDPool(
			id INTEGER PRIMARY KEY,
			rfid_uid TEXT NOT NULL,
			spotify_URI TEXT NOT NULL,
			play_nb UNSIGNED INTEGER DEFAULT 1
		)
		""")

	conn.commit()

	return conn, cursor

def addToDB(conn, cursor, reader, spotify_URI):
	rfid_uid, _ = reader.read()

	cursor.execute("""
		INSERT INTO RFIDPool(rfid_uid, spotify_URI)
              VALUES(?,?) 
		""", (rfid_uid, spotify_URI))

	conn.commit()


try:
	# Initialization
	sp = authenticateSpotify()
	print('Connected to Spotify')
	conn, cursor = connectDatabase(config.DBFilename)
	print('Connected to DB')
	reader = SimpleMFRC522()
	print('RFID reader ready')


	addToDB(conn, cursor, reader, 'spotify:album:6cjXNVPvBuQdrCbllisAbD')

	# Play songs
	while True:
		rfid_uid, _ = reader.read()
		cursor.execute("SELECT spotify_URI, play_nb FROM RFIDPool WHERE rfid_uid={}".format(rfid_uid))
    	result = cursor.fetchone()

    	if cursor.rowcount == 0:
    		print('Unregistered RFID card')
    	else: 
    		spotify_URI, play_nb = result[0], result[1]
    		#Example URI : spotify:album:6cjXNVPvBuQdrCbllisAbD
    		
    		#Play the URI at the requested spot:
    		start_playback(context_uri=spotify_URI, offset=None)

			#Increase the counter
			cursor.execute("""
				UPDATE tasks
	            	SET play_nb = ? ,
	            WHERE rfid_uid = ?
				""", (play_nb+1, rfid_uid))
			conn.commit()

finally:
	GPIO.cleanup() #Ensures it's always clean
	conn.close() #Close the connection to the DB


