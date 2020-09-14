# Some needed libraries
import sys
import pprint
import time

# The spotify wrapper to request the API
import spotipy.util as util
import spotipy.oauth2 as oauth2
import spotipy

# The config for the Spotfiy API and for the DB
import config

# The functions necessary to read the RFID tag
from pirc522 import RFID
import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BOARD)

# The volume button class
from volume_button import VolumeButton

# Handles the link with the DB holding the spotify song/album/artist ID
import sqlite3

#For the buttons and the events
import threading

class RFIDfy:
	addToDBButtonPin = 40 #GPIO21

	addToDBLedPin = 7 #GPIO4
	playingLedPin = 11 #GPIO17
	systemEventLedPin = 12 #GPIO18

	nextTrackButtonPin = 13 #GPIO27
	prevTrackButtonPin = 15 #GPIO22
	playPauseTrackButtonPin = 16 #GPIO23
	RFIDPin = None #IRQ Pin, set later.
	selector1Pin = 35 #GPIO19
	selector2Pin = 36 #GPIO16
	selector3Pin = 37 #GPIO26
	selector4Pin = 38 #GPIO20

	volumeIncrement = 5 #In %
	volumePinA = 29 # GPIO 5
	volumePinB = 31 # GPIO 6

	def __init__(self):
		self.addToDBButtonEvent = threading.Event() #Detects the press of a button
		self.playingEvent = threading.Event() #Detects the next / previous event button
		self.checkIfPlayingFlag = threading.Event() #Flag active when the threadPlayCheck needs to stop
		self.checkAssociateTypeFlag = threading.Event() #Flag active when the threadAssociateCheck needs to stop
		self.killSwitchFlag = threading.Event() #Flag active when the all processes/threads/loops in the class needs to stop


		GPIO.setup(self.addToDBButtonPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.add_event_detect(self.addToDBButtonPin, GPIO.FALLING, callback=self.addToDBEventDetected, bouncetime=500)
		
		GPIO.setup(self.nextTrackButtonPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.add_event_detect(self.nextTrackButtonPin, GPIO.FALLING, callback=self.prevNextEventDetected, bouncetime=500)
		
		GPIO.setup(self.prevTrackButtonPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.add_event_detect(self.prevTrackButtonPin, GPIO.FALLING, callback=self.prevNextEventDetected, bouncetime=500)

		GPIO.setup(self.playPauseTrackButtonPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.add_event_detect(self.playPauseTrackButtonPin, GPIO.BOTH, callback=self.prevNextEventDetected, bouncetime=500)
		
		GPIO.setup(self.addToDBLedPin, GPIO.OUT, initial=GPIO.LOW)
		GPIO.setup(self.playingLedPin, GPIO.OUT, initial=GPIO.LOW)
		GPIO.setup(self.systemEventLedPin, GPIO.OUT, initial=GPIO.LOW)

		GPIO.setup(self.selector1Pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.setup(self.selector2Pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.setup(self.selector3Pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.setup(self.selector4Pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.add_event_detect(self.selector1Pin, GPIO.FALLING, callback=self.associateTypeChange, bouncetime=500)
		GPIO.add_event_detect(self.selector2Pin, GPIO.FALLING, callback=self.associateTypeChange, bouncetime=500)
		GPIO.add_event_detect(self.selector3Pin, GPIO.FALLING, callback=self.associateTypeChange, bouncetime=500)
		GPIO.add_event_detect(self.selector4Pin, GPIO.FALLING, callback=self.associateTypeChange, bouncetime=500)

		self.authenticateSpotify() #sets self.sp and self.credentials
		print('Connected to Spotify')
		
		self.connectDatabase() #sets self.conn & self.cursor
		print('Connected to DB')
		self.reader = RFID()
		RFIDfy.RFIDPin = self.reader.pin_irq
		self.tagEvent = self.reader.irq
		print('RFID reader ready')

		self.associateType = 'track' #playlist or artist or album
		
		self.volume = 50 #between 0 and 100%
		self.volumeButton = VolumeButton(self.volumePinA, self.volumePinB, self.volumeButtonCallback)

	#------------------ Hardware related functions
	def start(self):
		thread1 = threading.Thread(target = self.blinkLed, args = (self.playingLedPin,))
		thread1.start()
		thread2 = threading.Thread(target = self.blinkLed, args = (self.systemEventLedPin,))
		thread2.start()
		thread2.join()
		GPIO.output(self.playingLedPin, GPIO.HIGH)

		self.startPlaying()
		#self.setRaspberryAsActiveDevice()

		try :
			self.sp.shuffle(True)
		except :
			print('Impossible to shuffle...')

		threadPlayCheck = threading.Thread(target = self.checkIfPlaying)
		threadPlayCheck.start()
		threadAssociateCheck = threading.Thread(target = self.checkAssociateType)
		threadAssociateCheck.start()

		# Main loop
		try : 
			while True:
				print('Waiting for event (button, RFID Tag)...')
				self.waitForEvent()
				if self.killSwitchFlag.isSet():
					print('End RFIDfy process.')
					break

		except spotipy.client.SpotifyException as spError:
			print('Spotify Error', str(spError))
			self.refreshToken() #TODO
			thread2 = threading.Thread(target = self.blinkLed, args = (self.systemEventLedPin,), kwargs={'intervalOn': 0.2, 'intervalOff' : 0.2, 'times' : 2})
			thread2.start()
			thread2.join()
			self.start()

		except KeyboardInterrupt :
			thread3 = threading.Thread(target = self.blinkLed, args = (self.systemEventLedPin,))
			thread3.start()
			thread3.join()
			self.cancel()
			raise

	def cancel(self):
		self.killSwitchFlag.set() #stop self.start() loop
		self.pauseMusic()
		self.reader.cancel()
		self.volumeButton.cancel()

		#end all threads
		self.checkIfPlayingFlag.set()
		self.checkAssociateTypeFlag.set()

		#remove all event detect from the RFIDfy object
		GPIO.remove_event_detect(self.addToDBButtonPin)
		GPIO.remove_event_detect(self.nextTrackButtonPin)
		GPIO.remove_event_detect(self.prevTrackButtonPin)
		GPIO.remove_event_detect(self.playPauseTrackButtonPin)
		GPIO.remove_event_detect(self.selector1Pin)
		GPIO.remove_event_detect(self.selector2Pin)
		GPIO.remove_event_detect(self.selector3Pin)
		GPIO.remove_event_detect(self.selector4Pin)


	def addToDBEventDetected(self, pinNb): # Press of a button
		self.addToDBButtonEvent.set()

	def tagEventDetected(self, pinNb): # Tag detected
		self.reader.irq_callback()

	def prevNextEventDetected(self, pinNb):# next previous track
		if pinNb == self.nextTrackButtonPin or pinNb == self.prevTrackButtonPin: 
		# If we pressed the next or prev button
			threadPlay = threading.Thread(target = self.blinkLedStayOn, args = (self.playingLedPin,))
			threadPlay.start()
			
			if pinNb == self.nextTrackButtonPin:
				self.playNextTrack()
			elif pinNb == self.prevTrackButtonPin:
				self.prevOrRestartTrack()
			
		elif pinNb == self.playPauseTrackButtonPin:
		# if we pressed the play pause button
			self.playPauseSwitch()

	def waitForEvent(self):
		self.reader.init()
		self.tagEvent.clear()
		self.reader.dev_write(0x04, 0x00)
		self.reader.dev_write(0x02, 0xA0)
		# Wait for it
		waiting = True

		while not self.killSwitchFlag.isSet() and waiting:
			self.reader.init()
			self.reader.dev_write(0x04, 0x00)
			self.reader.dev_write(0x02, 0xA0)

			self.reader.dev_write(0x09, 0x26)
			self.reader.dev_write(0x01, 0x0C)
			self.reader.dev_write(0x0D, 0x87)
			waiting = (not self.tagEvent.wait(0.1)) and (not self.addToDBButtonEvent.wait(0.1))
		self.reader.init()

		if self.tagEvent.isSet(): #We read a tag
			self.playRFIDTag()
			time.sleep(2)


		elif self.addToDBButtonEvent.isSet(): # there was a Link event
			GPIO.output(self.addToDBLedPin, GPIO.HIGH)
			self.getCurrentlyPlayingURI()
			rfid_uid = self.reader.wait_for_tag_uid(timeout = 5)
			print('Tag UID: ', rfid_uid)
			if rfid_uid != None:
				self.addCurrentlyPlayingToDB(rfid_uid)
				GPIO.output(self.addToDBLedPin, GPIO.LOW)
				self.blinkLed(self.addToDBLedPin)
				time.sleep(2)
			else:
				thread1 = threading.Thread(target = self.blinkLed, args = (self.systemEventLedPin,), kwargs = {'intervalOn': 1, 'intervalOff' : 0.1, 'times' : 2})
				thread1.start()
			GPIO.output(self.addToDBLedPin, GPIO.LOW)

		self.tagEvent.clear()
		self.addToDBButtonEvent.clear()

	def blinkLed(self, pin, times = 4, intervalOn = 0.1, intervalOff = 0.1):
		for _ in range(times):
			GPIO.output(pin, GPIO.HIGH)
			time.sleep(intervalOn)
			GPIO.output(pin, GPIO.LOW)
			time.sleep(intervalOff)

	def blinkLedStayOn(self, pin, times = 4, intervalOn = 0.1, intervalOff = 0.1):
		for _ in range(times):
			GPIO.output(pin, GPIO.HIGH)
			time.sleep(intervalOn)
			GPIO.output(pin, GPIO.LOW)
			time.sleep(intervalOff)
		GPIO.output(pin, GPIO.HIGH)

	def checkIfPlaying(self):
		#Checks if playing on spotify API every 5s (in case of manual play / pause)
		while not self.checkIfPlayingFlag.isSet():
			result = self.sp.currently_playing()
			if result and result['is_playing']:
				GPIO.output(self.playingLedPin, GPIO.HIGH)
			else:
				GPIO.output(self.playingLedPin, GPIO.LOW)
			self.checkIfPlayingFlag.wait(5)

	def checkAssociateType(self):
		#Run every 10s to check the type of association in case of an error with the selector system
		while not self.checkAssociateTypeFlag.isSet():
			if not GPIO.input(self.selector2Pin):
				self.associateType = 'playlist'
			elif not GPIO.input(self.selector3Pin):
				self.associateType = 'artist'
			elif not GPIO.input(self.selector4Pin):
				self.associateType = 'album'
			else:
				self.associateType = 'track'

			self.checkAssociateTypeFlag.wait(10)

	def associateTypeChange(self, pin):
		if pin == self.selector2Pin:
			self.associateType = 'playlist'
		elif pin == self.selector3Pin:
			self.associateType = 'artist'
		elif pin == self.selector4Pin:
			self.associateType = 'album'
		else:
			self.associateType = 'track'

		print('Current type {}'.format(self.associateType))


	#------------------ Software related functions
	def authenticateSpotify(self):
		#----- The app authentication
		CLIENT_ID =  config.CLIENT_ID
		CLIENT_SECRET = config.CLIENT_SECRET
		USERNAME = config.USERNAME
		scope = config.scope
		redirect_uri = config.redirect_uri

		#self.credentials = oauth2.SpotifyClientCredentials(client_id=CLIENT_ID,
		#        		client_secret=CLIENT_SECRET)
		#token = self.credentials.get_access_token()

		token = util.prompt_for_user_token(USERNAME, scope, client_id=CLIENT_ID, \
		client_secret=CLIENT_SECRET, redirect_uri=redirect_uri)

		if token: #To refactor
			self.sp = spotipy.Spotify(auth=token)

		else:
			print("Authenticating to Spotify failed. \nCan't get token for {}, \
				check your credentials.".format(USERNAME))
			sys.exit(-1)

	def refreshToken(self):
		cachedToken = self.credentials.get_cached_token()
		refreshedToken = cached_token['refresh_token']
		newToken = self.credentials.refresh_access_token(refreshed_token)

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
		print('setRaspberryAsActiveDevice', result, config.DEVICE_NAME)
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
			print('Card already associated with this URI.')
		else: 
		#First time we assign this card
			self.cursor.execute("""
				INSERT INTO RFIDPool(rfid_uid, spotify_URI)
					  VALUES(?,?) 
				""", (rfid_uid, spotify_URI))

			self.conn.commit()
			print('Card added.')

	def getCurrentlyPlayingURI(self):
		result = self.sp.currently_playing()
		# {u'context': {u'external_urls': {u'spotify': u'https://open.spotify.com/playlist/08A6NYKrsgPZ9VhCK1O80H'},
		#               u'href': u'https://api.spotify.com/v1/playlists/08A6NYKrsgPZ9VhCK1O80H',
		#               u'type': u'playlist',
		#               u'uri': u'spotify:user:val34322:playlist:08A6NYKrsgPZ9VhCK1O80H'},
		#  u'currently_playing_type': u'track',
		#  u'is_playing': True,
		#  u'item': {u'album': {u'album_type': u'album',
		#                       u'artists': [...],
		#                       u'type': u'album',
		#                       u'uri': u'spotify:album:5zj0qH4lKPQOotmWkE3ECb'},
		#            u'artists': [{u'external_urls': {u'spotify': u'https://open.spotify.com/artist/2nq2BeSbzExGAv3Y4HgUf7'},
		#                          u'href': u'https://api.spotify.com/v1/artists/2nq2BeSbzExGAv3Y4HgUf7',
		#                          u'id': u'2nq2BeSbzExGAv3Y4HgUf7',
		#                          u'name': u'Stephan Bodzin',
		#                          u'type': u'artist',
		#                          u'uri': u'spotify:artist:2nq2BeSbzExGAv3Y4HgUf7'}],
		#            u'type': u'track',
		#            u'uri': u'spotify:track:0yuJtvXsapVOQfNDYxQ5mw'},
		#  u'progress_ms': 8379,
		#  u'timestamp': 1583699924931L}
		spotify_URI = None
		if self.associateType == 'track' and result and result['item']:
			spotify_URI = result['item']['uri']
		elif self.associateType == 'artist'and result and result['item'] and result['item']['artists']:
			spotify_URI = result['item']['artists'][0]['uri']
		elif self.associateType == 'playlist'and result and result['context'] and 'playlist' in result['context']['uri']:
			spotify_URI = result['context']['uri']
		elif self.associateType == 'album'and result and result['item'] and result['item']['album']:
			spotify_URI = result['item']['album']['uri']

		return spotify_URI

	def addCurrentlyPlayingToDB(self, rfid_uid):
		spotify_URI = self.getCurrentlyPlayingURI()
		print('addCurrentlyPlayingToDB :', spotify_URI)
		if spotify_URI:
			self.addToDB(spotify_URI, rfid_uid)

	def startPlaying(self):
		result = self.sp.currently_playing()
		if result and not result['is_playing']:
			self.sp.start_playback()

	def playRFIDTag(self):
		#Play the URI at the requested spot

		rfid_uid = self.reader.wait_for_tag_uid()
		print('playRFIDTag - Tag UID: ', rfid_uid)
		if rfid_uid:
			self.cursor.execute("SELECT spotify_URI, play_nb FROM RFIDPool WHERE rfid_uid = ?", (rfid_uid,))
			result = self.cursor.fetchone()
			if self.cursor.rowcount == 0 or result == None:
				thread1 = threading.Thread(target = self.blinkLed, args = (self.systemEventLedPin,))
				thread1.start()
				print('Unregistered RFID card')
			else: 
				spotify_URI, play_nb = result[0], result[1]
				#Example URI : 'spotify:album:6cjXNVPvBuQdrCbllisAbD'

				print('RFID URI read : {} {}'.format(spotify_URI, play_nb))

				currentlyPlayingURI = self.getCurrentlyPlayingURI()
				if spotify_URI == currentlyPlayingURI: #Already playing
					thread1 = threading.Thread(target = self.blinkLedStayOn, args = (self.playingLedPin,), kwargs = {'intervalOn': 0.1, 'intervalOff' : 0.1, 'times' : 2})
					thread1.start()
				elif spotify_URI != currentlyPlayingURI and 'track' in spotify_URI: #if not already playing...
					#Play the URI at the requested spot:
					self.sp.start_playback(uris=[spotify_URI], offset=None)
					#Blink playingLedPin
					thread1 = threading.Thread(target = self.blinkLedStayOn, args = (self.playingLedPin,))
					thread1.start()

					# #Add same songs to queue
					# reco = self.sp.recommendations(seed_tracks=[spotify_URI])
					# if reco :
					# 	for track in reco['tracks']:
					# 		self.sp.add_to_queue(track['uri'])
							
				elif 'track' not in spotify_URI:#For playlists, artists, ...
					#Play the URI at the requested spot:
					self.sp.start_playback(context_uri=spotify_URI, offset=None)
					#Blink playingLedPin
					thread1 = threading.Thread(target = self.blinkLedStayOn, args = (self.playingLedPin,))
					thread1.start()
				else: #Other system error
					thread1 = threading.Thread(target = self.blinkLed, args = (self.systemEventLedPin,))
					thread1.start()

				if spotify_URI != currentlyPlayingURI:
					#Increase the counter
					self.cursor.execute("UPDATE RFIDPool SET play_nb = ? WHERE rfid_uid = ?", (play_nb+1, rfid_uid))
					self.conn.commit()
		else :
			thread1 = threading.Thread(target = self.blinkLed, args = (self.systemEventLedPin,), kwargs = {'intervalOn': 1, 'intervalOff' : 0.1, 'times' : 2})
			thread1.start()

	def playNextTrack(self):
		self.sp.next_track()
		self.startPlaying()

	def prevOrRestartTrack(self):
		result = self.sp.currently_playing()
		if result['is_playing'] and result['progress_ms'] > 10000: 
		#playing for more than 10s we restart the track
			self.sp.seek_track(0)
		else:
			try:
				self.sp.previous_track() #Will fail if no previous track
				self.startPlaying()
			except:
				print('Fail no previous track.')
				self.sp.seek_track(0)

	def playPauseSwitch(self):
		threadPlay = threading.Thread(target = self.blinkLedStayOn, args = (self.playingLedPin,))
		threadPause = threading.Thread(target = self.blinkLed, args = (self.playingLedPin,))
		result = self.sp.currently_playing()
		if not result['is_playing']:
			threadPlay.start()
			self.sp.start_playback()
		elif result['is_playing']:
			threadPause.start()
			self.sp.pause_playback()

	def pauseMusic(self):
		result = self.sp.currently_playing()
		if result['is_playing']:
			GPIO.output(self.playingLedPin, GPIO.LOW)
			self.sp.pause_playback()

	def volumeButtonCallback(self, direction): #direction always -1 or +1
		if direction == 1:
			self.volume = max(self.volume-self.volumeIncrement, 0)
		else:
			self.volume = min(self.volume+self.volumeIncrement, 100)
		self.sp.volume(self.volume)


# Box can handle the error of the RFIDfy object and is in charge of the power button.
class Box : #long press should turn off the thing...
	def __init__(self):
		self.RFIDfy = None
		self.resetButtonPin = 33 #GPIO13
		self.stateFlag = threading.Event()
		self.stateFlag.set() # because we want the RFIDfy object to run
		self.state = 'ON' #or 'OFF'

		self.setupResetButton()

	def RFIDfyOff(self):
		self.RFIDfy.cancel()
		#end main RFIDfy thread
		#end all other threads (checkIfPlaying, checkAssociateType)
		#self.RFIDfy.checkIfPlayingFlag.set()
		self.state = 'OFF'

	def RFIDfyOn(self):
		self.stateFlag.set() #Lets start over
		self.state = 'ON'

	def powerOn(self):
		while True :
			print('-------- Waiting to be turned ON...')
			if self.stateFlag.wait(5): #Blocking until self.RFIDfyOn is called
				print('-------- New instance created')
				self.stateFlag.clear()
				try:
					self.RFIDfy = RFIDfy()
					self.RFIDfy.start()
				except KeyboardInterrupt : #We want to stop looping 
					break
				except:
					raise
				finally:
					print('-------- Cleaning up...')

	def setupResetButton(self):
		GPIO.setup(self.resetButtonPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.add_event_detect(self.resetButtonPin, GPIO.FALLING, callback=self.RFIDfyOnOff, bouncetime=1000)


	def RFIDfyOnOff(self, pinNb):
		# self.RFIDfy.killSwitchFlag.set()
		# self.RFIDfy.checkIfPlayingFlag.set()
		# self.RFIDfy.checkAssociateTypeFlag.set()

		# self.resetFlag.set() #lets start over
		if self.state == 'ON':
			print('-------- Going OFF')
			self.RFIDfyOff()
		else :
			print('-------- Going ON')
			self.RFIDfyOn()
			

if __name__ == "__main__":
	box = Box()
	box.powerOn()
	GPIO.cleanup() #Ensures it's always clean