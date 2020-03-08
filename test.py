from pirc522 import RFID
rdr = RFID()

try:
	while True:
		rdr.wait_for_tag()
		(error, tag_type) = rdr.request()
		print(error, tag_type)
		if not error:
			print("Tag detected")
			(error, uid) = rdr.anticoll()
			if not error:
				print("UID: " + str(uid))

except:
	raise
finally:
	# Calls GPIO cleanup
	rdr.cleanup()

# import RPi.GPIO as GPIO
# from mfrc522 import SimpleMFRC522

# reader = SimpleMFRC522()

# try:
#         id = reader.read_id()
#         print(id)
# finally:
#         GPIO.cleanup()