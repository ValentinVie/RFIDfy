# Some needed libraries
import sys
import pprint
import time

# The spotify wrapper to request the API
import spotipy.util as util
import spotipy

# The config for the Spotfiy API and for the DB
import config

# The functions necessary to read the RFID tag
from pirc522 import RFID
import RPi.GPIO as GPIO

# Handles the link with the DB holding the spotify song/album/artist ID
import sqlite3

#For the buttons and the events
import threading

class RFIDfy:
	addToDBButtonEvent = threading.Event() #Detects the press of a button

	addToDBButtonPin = 40 #GPIO21
	RFIDPin = None #IRQ Pin

	def __init__(self):
		GPIO.setmode(GPIO.BOARD)
		GPIO.setup(RFIDfy.addToDBButtonPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.add_event_detect(RFIDfy.addToDBButtonPin, GPIO.FALLING, callback=self.addToDBEventDetected, bouncetime=500)

		self.authenticateSpotify() #sets self.sp
		print('Connected to Spotify')
		
		self.connectDatabase() #sets self.conn & self.cursor
		print('Connected to DB')
		self.reader = RFID()
		RFIDfy.RFIDPin = self.reader.pin_irq
		self.tagEvent = self.reader.irq
		print('RFID reader ready')

	#------------------ Hardware related functions
	def start(self):
		self.setRaspberryAsActiveDevice()

		while True:
			print('Waiting for event (button, RFID Tag)...')
			self.waitForEvent()

	def addToDBEventDetected(self, pinNb): # Press of a button
		self.addToDBButtonEvent.set()

	def tagEventDetected(self, pinNb): # Tag detected
		self.reader.irq_callback()


	def waitForEvent(self):
		self.reader.init()
		self.tagEvent.clear()
		self.reader.dev_write(0x04, 0x00)
		self.reader.dev_write(0x02, 0xA0)
		# Wait for it
		waiting = True

		while waiting:
			self.reader.init()
			self.reader.dev_write(0x04, 0x00)
			self.reader.dev_write(0x02, 0xA0)

			self.reader.dev_write(0x09, 0x26)
			self.reader.dev_write(0x01, 0x0C)
			self.reader.dev_write(0x0D, 0x87)
			waiting = (not self.tagEvent.wait(0.1)) and (not self.addToDBButtonEvent.wait(0.1))
		self.reader.init()

		if self.tagEvent.isSet():
			self.playRFIDTag()
			time.sleep(2)
		else: #self.addToDBButtonEvent.isSet() == True
			print('---addToDBButtonEvent')
			rfid_uid = self.reader.wait_for_tag_uid(timeout = 5)
			if rfid_uid != None:
				self.addCurrentlyPlayingToDB(rfid_uid)
				time.sleep(2)


		self.tagEvent.clear()
		self.addToDBButtonEvent.clear()



	#------------------ Software related functions
	def authenticateSpotify(self):
		#----- The app authentication
		CLIENT_ID =  config.CLIENT_ID
		CLIENT_SECRET = config.CLIENT_SECRET
		USERNAME = config.USERNAME
		scope = config.scope
		redirect_uri = config.redirect_uri


		token = util.prompt_for_user_token(USERNAME, scope, client_id=CLIENT_ID, \
		client_secret=CLIENT_SECRET, redirect_uri=redirect_uri)

		if token:
			self.sp = spotipy.Spotify(auth=token)
		else:
			print("Authenticating to Spotify failed. \nCan't get token for {}, \
				check your credentials.".format(USERNAME))
			sys.exit(-1)

	def connectDatabase(self):
		self.conn = sqlite3.connect(config.DBFilename)
		self.cursor = self.conn.cursor()

		#Creating the DB if it doesnt exist
		self.cursor.execute("""
			CREATE TABLE IF NOT EXISTS RFIDPool(
				id INTEGER PRIMARY KEY,
				rfid_uid TEXT NOT NULL,
				spotify_URI TEXT NOT NULL,
				play_nb UNSIGNED INTEGER DEFAULT 1
			)
			""")

		self.conn.commit()


	def setRaspberryAsActiveDevice(self):
		result = self.sp.devices()
		print(result, config.DEVICE_NAME)
		for device in result['devices']:
			if device['name'] == config.DEVICE_NAME and not device['is_active']:
				#We need to activate the device
				self.sp.transfer_playback(device['id'])


	def addToDB(self, spotify_URI, rfid_uid):
		#addToDB(conn, cursor, reader, 'spotify:album:6cjXNVPvBuQdrCbllisAbD')	
		#Add to DB and check for duplicate
		self.cursor.execute("SELECT spotify_URI FROM RFIDPool WHERE rfid_uid = ?", (rfid_uid,))
		result = self.cursor.fetchone()
		if result and result[0] != spotify_URI: 
		#There is already a different URI associated with the rfid_uid, we replace it
			self.cursor.execute("UPDATE RFIDPool SET spotify_URI = ?, play_nb = ? WHERE rfid_uid = ?", (spotify_URI, 1, rfid_uid))
			self.conn.commit()
			print('Card re-assigned.')
		elif result and result[0] == spotify_URI:
			print('Card already associated.')
		else: 
		#First time we assign this card
			self.cursor.execute("""
				INSERT INTO RFIDPool(rfid_uid, spotify_URI)
					  VALUES(?,?) 
				""", (rfid_uid, spotify_URI))

			self.conn.commit()
			print('Card added.')

	def addCurrentlyPlayingToDB(self, rfid_uid):
		result = self.sp.currently_playing()
		 # u'context': {u'external_urls': {u'spotify': u'https://open.spotify.com/artist/4LXBc13z5EWsc5N32bLxfH'},
		 #			  u'href': u'https://api.spotify.com/v1/artists/4LXBc13z5EWsc5N32bLxfH',
		 #			  u'type': u'artist',
		 #			  u'uri': u'spotify:artist:4LXBc13z5EWsc5N32bLxfH'},
		 # u'context': {u'external_urls': {u'spotify': u'https://open.spotify.com/playlist/6pnEs66ugTnOY4PvjmUqY0'},
		 #			  u'href': u'https://api.spotify.com/v1/playlists/6pnEs66ugTnOY4PvjmUqY0',
		 #			  u'type': u'playlist',
		 #			  u'uri': u'spotify:user:val34322:playlist:6pnEs66ugTnOY4PvjmUqY0'},
		
		if result['context']:
			spotify_URI = result['context']['uri']
		elif result['item']:
			spotify_URI = result['item']['uri']
		
		if spotify_URI:
			self.addToDB(spotify_URI, rfid_uid)

	def playRFIDTag(self):
		#Play the URI at the requested spot

		rfid_uid = self.reader.wait_for_tag_uid()
		self.cursor.execute("SELECT spotify_URI, play_nb FROM RFIDPool WHERE rfid_uid = ?", (rfid_uid,))
		result = self.cursor.fetchone()

		if self.cursor.rowcount == 0:
			print('Unregistered RFID card')
		else: 
			spotify_URI, play_nb = result[0], result[1]
			#Example URI : spotify:album:6cjXNVPvBuQdrCbllisAbD

			print('RFID read : {} {}'.format(spotify_URI, play_nb))

			#Play the URI at the requested spot:
			if 'track' in spotify_URI:
				self.sp.start_playback(uris=[spotify_URI], offset=None)
			else:
				self.sp.start_playback(context_uri=spotify_URI, offset=None)

			#Increase the counter
			self.cursor.execute("UPDATE RFIDPool SET play_nb = ? WHERE rfid_uid = ?", (play_nb+1, rfid_uid))
			self.conn.commit()
try:
	box = RFIDfy()
	box.start()
except:
	raise
finally:
	print('Cleaning up...')
	GPIO.cleanup() #Ensures it's always clean
	#conn.close() #Close the connection to the DB

# # Play songs
# while True:

# 	#Calls handle event and then returns...


# 	rfid_uid = reader.waitForTagUID()
# 	cursor.execute("SELECT spotify_URI, play_nb FROM RFIDPool WHERE rfid_uid = ?", (rfid_uid,))
# 	result = cursor.fetchone()

# 	if cursor.rowcount == 0:
# 		print('Unregistered RFID card')
# 	else: 
# 		spotify_URI, play_nb = result[0], result[1]
# 		#Example URI : spotify:album:6cjXNVPvBuQdrCbllisAbD

# 		print('RFID read : {} {}'.format(spotify_URI, play_nb))

# 		#Play the URI at the requested spot:
# 		#sp.start_playback(context_uri=spotify_URI, offset=None)

# 		#Increase the counter
# 		cursor.execute("UPDATE RFIDPool SET play_nb = ? WHERE rfid_uid = ?", (play_nb+1, rfid_uid))
# 		conn.commit()

# 	 # Wait 2s before reading another tag




