#!/usr/bin/env python
import RPi.GPIO as GPIO

class VolumeButton:

	"""Class to decode mechanical rotary encoder pulses."""

	def __init__(self, gpioA, gpioB, callbackFunction):

		"""
		https://www.sunfounder.com/learn/Super_Kit_V2_for_RaspberryPi/lesson-8-rotary-encoder-super-kit-for-raspberrypi.html
		Instantiate the class with the pi and gpios connected to
		rotary encoder contacts A and B.  The common contact
		should be connected to ground.  The callback is
		called when the rotary encoder is turned.  It takes
		one parameter which is +1 for clockwise and -1 for
		counterclockwise.
		"""

		self.gpioA = gpioA
		self.gpioB = gpioB
		self.callbackFunction = callbackFunction

		self.levA = 0
		self.levB = 0

		self.lastGpio = None

		GPIO.setup(self.gpioA, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.setup(self.gpioB, GPIO.IN, pull_up_down=GPIO.PUD_UP)

		GPIO.add_event_detect(self.gpioA, GPIO.BOTH, callback=self._decode)
		GPIO.add_event_detect(self.gpioB, GPIO.BOTH, callback=self._decode)


	def _decode(self, channel):
		"""
		Decode the rotary encoder pulse.

		+---------+         +---------+      1
		|         |         |         |
		A         |         |         |         |
		|         |         |         |
		+---------+         +---------+         +----- 0

		+---------+         +---------+            1
		|         |         |         |
		B   |         |         |         |
		|         |         |         |
		----+         +---------+         +---------+  0
		"""
		level = GPIO.input(channel)
		if channel == self.gpioA:
			self.levA = level
		else:
			self.levB = level
		#print(self.lastGpio, channel, self.levA, self.levB)

		# Debounce.
		if channel == self.lastGpio:
			return

		# When both inputs are at 1, we'll fire a callback. If A was the most
		# recent pin set high, it'll be forward, and if B was the most recent pin
		# set high, it'll be reverse.

		self.lastGpio = channel
		if channel == self.gpioA and level == 1:
			if self.levB == 1:
				self.callbackFunction(1)
		elif channel == self.gpioB and level == 1:
			if self.levA == 1:
				self.callbackFunction(-1)

	def cancel(self):
		"""
		Cancel the rotary encoder decoder.
		"""

		GPIO.remove_event_detect(self.gpioA)
		GPIO.remove_event_detect(self.gpioB)

if __name__ == "__main__":
	import RPi.GPIO as GPIO
	GPIO.setmode(GPIO.BOARD)
	import time

	pos = 0

	def callback(increment):
		global pos
		pos += increment
		print("pos={}".format(pos))

	gpioA = 29 # GPIO 5
	gpioB = 31 # GPIO 6
	decoder = VolumeButton(gpioA, gpioB, callback)

	time.sleep(300)

	decoder.cancel()

