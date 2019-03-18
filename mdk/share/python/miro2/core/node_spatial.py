#	@section COPYRIGHT
#	Copyright (C) 2019 Consequential Robotics Ltd
#	
#	@section AUTHOR
#	Consequential Robotics http://consequentialrobotics.com
#	
#	@section LICENSE
#	For a full copy of the license agreement, see LICENSE in the
#	MDK root directory.
#	
#	Subject to the terms of this Agreement, Consequential
#	Robotics grants to you a limited, non-exclusive, non-
#	transferable license, without right to sub-license, to use
#	MIRO Developer Kit in accordance with this Agreement and any
#	other written agreement with Consequential Robotics.
#	Consequential Robotics does not transfer the title of MIRO
#	Developer Kit to you; the license granted to you is not a
#	sale. This agreement is a binding legal agreement between
#	Consequential Robotics and the purchasers or users of MIRO
#	Developer Kit.
#	
#	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
#	KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
#	WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
#	PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS
#	OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
#	OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
#	OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
#	SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import numpy as np
import time
import copy
import multiprocessing

import cv2

import node

import miro2 as miro
import signals



class NodeSpatial(node.Node):

	def __init__(self, sys):

		node.Node.__init__(self, sys, "spatial")

		# resources
		self.lock = multiprocessing.Lock()

		# state
		self.jit_init_complete = False
		self.priority_peak = [
			signals.PriorityPeak(0),
			signals.PriorityPeak(1),
			signals.PriorityPeak(2)
		]

		# inputs
		self.audio_events = [[], [], []]
		self.frame_mov = [None, None]
		self.wide_field_elev = 0.0
		self.face = [None, None]

	def jit_init(self, stream_index, img_shape):

		# attempt to lock
		if not self.lock.acquire(False):

			# failed to lock, busy, so nothing we can do here
			print "jit_init busy in stream", stream_index, "(it is being run on the other camera stream)"
			return False

		# mutex is locked, now, check again if jit_init is already complete
		if self.jit_init_complete:

			# ok all done
			print "jit_init complete in stream", stream_index, "(already completed by the other camera stream when we got the mutex)"
			self.lock.release()
			return True

		# report
		print "jit_init started in stream", stream_index

		# recover dimensions from example image
		self.sx = img_shape[1]
		self.sy = img_shape[0]
		self.sw = 256

		# intialize camera model
		self.state.camera_model.set_frame_size(self.sx, self.sy)

		# test camera model
		#print self.state.camera_model.p2d([0.0, 0.0]).as_string()
		#miro.utils.error("stop")

		# initialize blank
		self.blank = np.zeros((self.sy, self.sx), np.float32)

		# initialize domes
		self.domes = []

		# initialize arrays for image streams
		self.pri  = [
			copy.copy(self.blank),
			copy.copy(self.blank),
			np.zeros((1, self.sw), np.float32)
		]

		# initialize wide field
		azim_max = (90.0 + self.pars.spatial.degrees_hindsight) * (np.pi / 180.0)
		azim_step = azim_max / (self.sw * 0.5)
		self.wide_azim = np.arange(azim_max-0.5*azim_step, -azim_max, -azim_step)

		# initialize camera field
		self.central_axis_azim = [None, None]
		self.central_axis_elev = [None, None]
		for stream_index in range(0, 2):

			central_axis_azim = np.zeros((self.sx))
			for xp in range(0, self.sx):
				p = [xp, self.sy * 0.5 - 0.5]
				v = self.state.camera_model.p2v(p)
				central_axis_azim[xp] = v.azim + self.pars.camera.azimuth[stream_index]
			self.central_axis_azim[stream_index] = central_axis_azim

			central_axis_elev = np.zeros((self.sy))
			for yp in range(0, self.sy):
				p = [self.sx * 0.5 - 0.5, yp]
				v = self.state.camera_model.p2v(p)
				central_axis_elev[yp] = v.elev + self.pars.camera.elevation[stream_index]
			self.central_axis_elev[stream_index] = central_axis_elev

		# report
		print "jit_init completed in stream", stream_index

		# mark completed
		self.jit_init_complete = True

		# release
		self.lock.release()

		# return completion state
		return True

	def get_dome(self, radius):

		# we store domes that we create, so we only have to create
		# them once at each radius
		for dome in self.domes:
			if dome[0] == radius:
				return dome[1]

		# create
		if not self.pars.flags.DEV_DEBUG_HALT: # do not pollute info
			print "create dome at radius", radius
		s = radius * 8 + 1
		dome = np.zeros((s, s), np.float32)

		# inject
		x = radius * 4
		dome[x, x] = 1.0

		# filter
		dome = cv2.GaussianBlur(dome, (0, 0), radius)

		# normalize
		dome *= (1.0 / np.max(dome))

		# store
		self.domes.append((radius, dome))

		# ok
		return dome

	def inject_pattern(self, frame, center, pattern):

		# get pattern size, assuming it is square
		sy = (pattern.shape[0] - 1) / 2
		sx = (pattern.shape[1] - 1) / 2

		# get source extent
		sx1 = 0
		sx2 = sx * 2 + 1
		sy1 = 0
		sy2 = sy * 2 + 1

		# get destination extent
		dx1 = center[0] - sx
		dx2 = center[0] + sx + 1
		dy1 = center[1] - sy
		dy2 = center[1] + sy + 1

		# constrain into destination
		sy = frame.shape[0]
		sx = frame.shape[1]
		if dx1 < 0:
			sx1 += (0 - dx1)
			dx1 = 0
		if dx2 > sx:
			sx2 += (sx - dx2)
			dx2 = sx
		if dy1 < 0:
			sy1 += (0 - dy1)
			dy1 = 0
		if dy2 > sy:
			sy2 += (sy - dy2)
			dy2 = sy

		# do injection
		frame[dy1:dy2, dx1:dx2] += pattern[sy1:sy2, sx1:sx2]

	def inject_dome(self, frame, center, radius, height):

		# simple in-fill of specified circle
		#cv2.circle(frame, center, radius, height, -1)

		# get dome
		dome = self.get_dome(radius) * height

		# inject into frame
		self.inject_pattern(frame, center, dome)

	def estimate_range(self, size_in_pix, size_in_m):

		# first, convert size_in_pix to normalised image size
		size_norm = float(size_in_pix) / self.pars.decode.image_width

		# normalise that by known size of object
		size_rel = size_norm / size_in_m

		# we could then retrieve the range from theory, but rather
		# than bother to actually figure it out (it is somewhat
		# dependent on the camera distortion model) I'm just going
		# to estimate it empirically for now
		if size_rel > 0.0:
			range = 0.4 / size_rel
			#print "est range", size_in_pix, size_in_m, range
		else:
			range = self.pars.action.range_estimate_max

		if range < self.pars.action.range_estimate_min:
			range = self.pars.action.range_estimate_min
		if range > self.pars.action.range_estimate_max:
			range = self.pars.action.range_estimate_max

		# ok
		return range

	def inject_face(self, stream_index):

		# extract and clear signal
		faces = self.state.detect_face[stream_index]
		self.state.detect_face[stream_index] = None

		# if signal is new
		if not faces is None:

			for face in faces:

				# extract
				rect = face[0:4]
				conf = face[4]

				# get range
				range = self.estimate_range(face[2], self.pars.action.face_size_m)

				# debug
				if not self.pars.flags.DEV_DEBUG_HALT: # do not pollute info
					print "face at range", range, "with conf", conf
				if self.pars.flags.DEV_DEBUG_DETECTION:
					self.output.tone = 255

				# paint in face
				x = int(face[0] + face[2] * 0.5)
				y = int(face[1] + face[3] * 0.5)
				r = (face[2] + face[3]) * 0.25
				m = int(self.pars.spatial.face_gain * conf * 255.0)

				# choose radius that reflects representational size
				# based on physical size in image
				r = int(r * 0.5)

				# inject stimulus
				self.inject_dome(self.pri[stream_index], (x, y), r, m)

				# store source
				p = [x, y]
				v = self.p2v(p, stream_index)
				self.sources.append([0, v, range])

	def inject_ball(self, stream_index):

		# extract and clear signal
		ball = self.state.detect_ball[stream_index]
		self.state.detect_ball[stream_index] = None

		# if signal is new
		if not ball is None:

			# get ball parameters
			x = ball[0]
			y = ball[1]
			r = ball[2]
			m = int(self.pars.spatial.ball_gain * 255.0)

			# get range
			range = self.estimate_range(r * 2, self.pars.action.ball_size_m)

			# debug
			if not self.pars.flags.DEV_DEBUG_HALT: # do not pollute info
				print "ball at range", range
			if self.pars.flags.DEV_DEBUG_DETECTION:
				self.output.tone = 253

			# choose radius that reflects representational size
			# based on physical size in image
			r = int(r * 0.5)

			# inject stimulus
			self.inject_dome(self.pri[stream_index], (x, y), r, m)

			# store source
			p = [x, y]
			v = self.p2v(p, stream_index)
			self.sources.append([1, v, range])

	def inject_motion(self, stream_index):

		# extract and clear signal
		frame_mov = self.frame_mov[stream_index]
		self.frame_mov[stream_index] = None

		# if signal is new
		if not frame_mov is None:
			if self.state.in_motion == 0 and self.state.in_blink == 0:
				frame_mov_mean = np.mean(frame_mov)
				self.pri[stream_index] += frame_mov - frame_mov_mean

	def inject_audio(self, stream_index):

		# extract and clear signal
		audio_events = self.audio_events[stream_index]
		self.audio_events[stream_index] = []

		# get gain
		gain = self.pars.spatial.audio_event_gain
		gain += self.state.in_making_noise * \
				(self.pars.spatial.audio_event_gain_making_noise - self.pars.spatial.audio_event_gain)

		# process audio events
		for audio_event in audio_events:

			# handle lr streams
			if stream_index < 2:

				# response in azim
				delta = audio_event.azim - self.central_axis_azim[stream_index]
				delta_sq = (delta * self.pars.spatial.audio_event_azim_size_recip) ** 2
				response_azim = np.exp(-delta_sq)

				# response in elev
				delta = audio_event.elev - self.central_axis_elev[stream_index]
				delta_sq = (delta * self.pars.spatial.audio_event_elev_size_recip) ** 2
				response_elev = np.exp(-delta_sq)

				# combine response
				response_azim = np.reshape(response_azim, (len(response_azim), 1))
				response_elev = np.reshape(response_elev, (len(response_elev), 1))
				response = np.dot(response_elev, response_azim.T)

			# handle wide stream
			if stream_index == 2:

				# response in azim
				delta = audio_event.azim - self.wide_azim
				delta_sq = (delta * self.pars.spatial.audio_event_azim_size_recip) ** 2
				response = np.exp(-delta_sq)

				# store elevation to be used in priority peak
				self.wide_field_elev = audio_event.elev

			# inject
			self.pri[stream_index] += (gain * 255.0 * audio_event.level) * response

	def publish_peak(self, peak):

		# attempt to lock
		if not self.lock.acquire(False):

			# failed to lock, someone else is doing it
			return

		# publish that
		self.state.priority_peak = peak

		# release
		self.lock.release()

	def find_best_peak(self):

		# find best peak
		best_peak = self.priority_peak[0]
		for j in range(1, 3):
			q = self.priority_peak[j]
			if q.height > best_peak.height:
				best_peak = q

		# ok
		return best_peak

	def set_priority_peak(self, stream_index, peak):

		with self.lock:
			self.priority_peak[stream_index] = peak

	def p2v(self, p, stream_index):

		# convert pixel location in IMAGE to view line in HEAD
		v = self.state.camera_model.p2v(p)
		v.azim += self.pars.camera.azimuth[stream_index]
		v.elev += self.pars.camera.elevation[stream_index]

		# ok
		return v

	def find_stream_peak(self, stream_index):

		# get image
		img = self.pri[stream_index]

		# find threshold for measuring size of priority region
		height = float(img.max())
		thresh = self.pars.spatial.pri_peak_height_thresh * height

		# and scale height into [0.0, 1.0]
		height *= (1.0 / 255.0)

		# find all points above threshold
		(y, x) = np.where(img > thresh)

		# describe region by centroid
		y_accum = sum(y)
		x_accum = sum(x)
		N_accum = len(x)

		# if nothing, we're done
		if N_accum == 0:

			# null peak
			self.set_priority_peak(stream_index, signals.PriorityPeak(stream_index))

		else:

			# centroid in pixel space
			p = [x_accum / N_accum, y_accum / N_accum]

			# handle camera streams
			if stream_index < 2:

				# convert to view line in HEAD
				v = self.p2v(p, stream_index)

				# size and height
				size = float(N_accum) / float(self.state.camera_model.frame_pixel_count)

				# create output
				self.set_priority_peak(stream_index,
						signals.PriorityPeak(stream_index, height, size, v.azim, v.elev))

			# handle wide stream
			else:

				# size and height
				size = float(N_accum) / float(self.sw)

				# get azim and elev
				azim = self.wide_azim[p[0]]
				elev = self.wide_field_elev

				# create output
				self.set_priority_peak(stream_index, \
					signals.PriorityPeak(stream_index, height, size, azim, elev))

		# return peak for this stream
		return self.priority_peak[stream_index]

	def process_stream(self, stream_index):

		# get our audio events
		q = self.state.audio_events_for_spatial
		self.state.audio_events_for_spatial = []

		# process audio events for all streams, regardless of
		# which stream we're processing right now; this is ok
		# because /any/ stream can do this, so long as it is
		# done as soon as the events are available from mics
		if len(q):
			for i in range(3):
				for event in q:
					self.audio_events[i].append(event)

		# do pri dynamics
		prif = cv2.GaussianBlur(self.pri[stream_index], (15, 15), 0)
		prif_mean = np.mean(prif)
		self.pri[stream_index] = self.pars.spatial.pri_decay_lambda * prif - prif_mean

		# clear sources
		self.sources = []

		# for camera streams
		if stream_index < 2:

			# inject motion detector output
			if self.pars.flags.SALIENCE_FROM_MOTION:
				self.inject_motion(stream_index)

			# inject detected balls
			if self.pars.flags.SALIENCE_FROM_BALL:
				self.inject_ball(stream_index)

			# inject faces
			if self.pars.flags.SALIENCE_FROM_FACES:
				self.inject_face(stream_index)

		# inject sound events
		if self.pars.flags.SALIENCE_FROM_SOUND:
			self.inject_audio(stream_index)

		# clip
		self.pri[stream_index] = np.clip(self.pri[stream_index], 0, 255)

		# find priority peak for this stream
		peak = self.find_stream_peak(stream_index)

		# review possible sources of peak
		peak.source_conf *= self.pars.spatial.pri_decay_lambda
		for source in self.sources:
			source_index = source[0]
			da = source[1].azim - peak.azim
			de = source[1].elev - peak.elev
			d = np.sqrt(da*da + de*de)
			conf = max(1.0 - d / self.pars.spatial.association_angle, 0.0)
			peak.source_conf[source_index] = max(peak.source_conf[source_index], conf)
			peak.source_range[source_index] = source[2]

		# find best peak across streams
		best_peak = self.find_best_peak()

		# finalize peak
		best_peak.finalize(self.pars)

		# publish best peak (now augmented with additional information)
		self.publish_peak(best_peak)

		# publish priority map (mostly for debug)
		self.state.frame_pri[stream_index] = self.pri[stream_index].astype(np.uint8)

	def tick_camera(self, stream_index):

		# return list of streams updated
		updated = []

		# get frame
		frame_mov = self.state.frame_mov[stream_index]

		# may be None during startup
		if frame_mov is None:
			return updated

		# ensure jit_init has been run
		if not self.jit_init_complete:
			if not self.jit_init(stream_index, frame_mov.shape):
				return updated

		# store frame for processing
		self.frame_mov[stream_index] = frame_mov

		# this also triggers processing of that stream
		self.process_stream(stream_index)
		updated.append(stream_index)

		# stream 0 also triggers processing of the wide stream
		if stream_index == 0:
			self.process_stream(2)
			updated.append(2)

		# ok
		return updated



