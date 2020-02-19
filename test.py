from pirc522 import RFID
rdr = RFID()

while True:
	rdr.wait_for_tag()
	print('OK1')
	rdr.wait_for_tag()
	print('OK2')
	(error, tag_type) = rdr.request()
	if not error:
		print("Tag detected")
		(error, uid) = rdr.anticoll()


# Calls GPIO cleanup
rdr.cleanup()