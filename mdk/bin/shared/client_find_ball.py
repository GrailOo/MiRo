#!/usr/bin/python

import rospy
import time
import sys
import os#
import datetime
import numpy as np

import miro2 as miro

import std_msgs
from geometry_msgs.msg import Pose2D
from geometry_msgs.msg import TwistStamped
from sensor_msgs.msg import JointState, BatteryState, Imu, Range, CompressedImage, Image

#Open CV
import cv2
from cv_bridge import CvBridge, CvBridgeError

################################################################

def error(msg):

    print(msg)
    sys.exit(0)

################################################################

class QLearningTable:
    def __init__(self, learning_rate=0.2, discount=0.9, e_greedy=0.9):
        self.lr = learning_rate
        self.gamma = discount
        self.epsilon = e_greedy

        self.num_states = np.array([5, 5])
        # self.states_low = np.array([-1.5,-1.5,-3.14])
        # self.states_high = np.array([1.5,1.5,3.14])
        # self.scale = np.array([0.5, 0.5, 1.57])
        self.num_actions = 6
        self.Q_table = np.zeros((self.num_states[0], self.num_states[1], self.num_actions))

    def print_Tabel(self):
        print('Q',self.Q_table)
        # print('E',self.E_table)

    def choose_action(self, state):
        return np.argmax(self.Q_table[state[0]][state[1]])
        # return np.argmax((1 - self.beta) * self.Q_table[state[0]][state[1]] + self.beta * self.E_table[state][0][state[1]])

    def learn(self, state, action, reward, new_state):
        self.Q_table[state[0]][state[1]][action] += self.lr * (
                reward + self.gamma * np.max(self.Q_table[new_state[0]][new_state[1]]) -
                self.Q_table[state[0]][state[1]][action])


################################################################

class client_findball:
    def callback_package(self, msg):

        self.sonar = msg.sonar.range
        # print "sonar", self.sonar
        # if self.sonar < 0.1:
        #     self.velocity.twist.linear.x = 0.0
        #     self.velocity.twist.angular.z = 0.0
        #     self.pub_cmd_vel.publish(self.velocity)

    def callback_pose(self, msg):

        self.pose = msg
        # print "received", mag

    def cam_left_callback(self, ros_image):
        try:
            self.cam_left_image = self.image_converter.compressed_imgmsg_to_cv2(ros_image, "bgr8")
            im_h, im_w = self.cam_left_image.shape[:2]
            if self.frame_w != im_w and self.frame_h != im_h:
                self.frame_w, self.frame_h = im_w, im_h
                self.cam_model.set_frame_size(self.frame_w, self.frame_h)
        except CvBridgeError as e:
             print("Conversion of left image failed \n")
             print(e)

    def cam_right_callback(self, ros_image):
        try:
            self.cam_right_image = self.image_converter.compressed_imgmsg_to_cv2(ros_image, "bgr8")
            im_h, im_w = self.cam_right_image.shape[:2]
            if self.frame_w != im_w and self.frame_h != im_h:
                self.frame_w, self.frame_h = im_w, im_h
                self.cam_model.set_frame_size(self.frame_w, self.frame_h)
        except CvBridgeError as e:
            print("Conversion of right image failed \n")
            print(e)


    def loop(self):

        # loop
        while not rospy.core.is_shutdown():

            f = lambda x, min_x: max(min_x, min(1.0, 1.0 - np.log10((x + 1) / 25.0)))

            for i in range(self.episode):
                print "i", i
                done = False
                state = self.get_state()

                step = 0

                while done != True:
                    if (np.random.random() < self.Q.epsilon):
                        action = self.action_space_sample()
                    else:
                        action = self.Q.choose_action(state)

                    # Get next state and reward
                    state2, reward, done = self.step(action)

                    # if self.sonar < 0.13:
                    #     reward = -5
                    #     done = True

                    if step > 100:
                        done = True

                    # Allow for terminal states
                    if done:
                        self.Q.Q_table[state[0], state[1], action] = reward
                    # Adjust Q value for current state
                    else:
                        self.Q.learn(state, action, reward, state2)

                    state = state2
                    step += 1
                    print "steps", step
                    print "reward", reward
                    time.sleep(0.01)

                self.Q.epsilon = f(i, 0.1)

            print self.Q.print_Tabel()


    def __init__(self):

        # config
        self.pose = []

        # Arrays to hold image topics
        self.cam_left_image = None
        self.cam_right_image = None

        # Create object to convert ROS images to OpenCV format
        self.image_converter = CvBridge()

        self.sonar = 0.58

        self.velocity = TwistStamped()
        self.action_space = ['PUSH', 'TURN_L_45', 'TURN_L_90', 'TURN_R_45', 'TURN_R_90', 'TURN_180']
        # 'TURN_L_135', 'TURN_R_135','STOP',
        self.goal = np.array([4, 2])
        self.episode = 100
        self.Q = QLearningTable()

        # robot name
        topic_base = "/" + os.getenv("MIRO_ROBOT_NAME") + "/"

        self.velocity = TwistStamped()

        self.pub_cmd_vel = rospy.Publisher(topic_base + "control/cmd_vel", TwistStamped, queue_size=0)


        # subscribe
        self.sub_mics = rospy.Subscriber(topic_base + "sensors/body_pose", Pose2D, self.callback_pose)
        print ("subscribe", topic_base + "sensors/body_pose")

        self.sub_package = rospy.Subscriber(topic_base + "sensors/package", miro.msg.sensors_package,self.callback_package)
        print ("subscribe", topic_base + "sensors/package")

        # Subscribe to Camera topics
        self.cam_left_sub = rospy.Subscriber(topic_base + "sensors/caml/compressed", CompressedImage,self.cam_left_callback)
        self.cam_right_sub = rospy.Subscriber(topic_base + "sensors/camr/compressed", CompressedImage,self.cam_right_callback)


        self.cam_model = miro.utils.CameraModel()
        self.frame_w = 0
        self.frame_h = 0

    def find_ball(self, colour_str, cam_id):
        # self.pause()
        if colour_str[0] != "#" and len(colour_str) != 7:
            print("colour choice should be a string in the form \"#RRGGBB\"")
            return
        if cam_id < 0 or cam_id > 1:
            return
        # if prop < 0 or prop > 2:
        #     return

        # create colour code from user selected colour
        red = int(colour_str[1:3], 16)
        green = int(colour_str[3:5], 16)
        blue = int(colour_str[5:7], 16)
        bgr_colour = np.uint8([[[blue, green, red]]])
        hsv_colour = cv2.cvtColor(bgr_colour, cv2.COLOR_BGR2HSV)

        # extract boundaries for masking image
        target_hue = hsv_colour[0, 0][0]
        lower_bound = np.array([target_hue - 20, 70, 70])
        upper_bound = np.array([target_hue + 20, 255, 255])

        if np.shape(self.cam_left_image) != () and np.shape(self.cam_right_image) != ():
            # convert camera image to HSV colour space
            if cam_id == miro.constants.CAM_L:
                hsv_image = cv2.cvtColor(self.cam_left_image, cv2.COLOR_BGR2HSV)
                output = self.cam_left_image.copy()
            else:
                hsv_image = cv2.cvtColor(self.cam_right_image, cv2.COLOR_BGR2HSV)
                output = self.cam_right_image.copy()
        else:
            return None

        im_h = np.size(hsv_image, 0)
        im_w = np.size(hsv_image, 1)
        im_centre_h = im_h / 2.0
        im_centre_w = im_w / 2.0
        cv2.line(output, (0, int(round(im_centre_h))), (im_w, int(round(im_centre_h))), (100, 100, 100), 1)
        cv2.line(output, (int(round(im_centre_w)), 0), (int(round(im_centre_w)), im_h), (100, 100, 100), 1)

        # mask image
        mask = cv2.inRange(hsv_image, lower_bound, upper_bound)
        seg = mask

        # Do some processing
        seg = cv2.GaussianBlur(seg, (11, 11), 0)
        seg = cv2.erode(seg, None, iterations=2)
        seg = cv2.dilate(seg, None, iterations=2)

        # get circles
        circles = cv2.HoughCircles(seg, cv2.HOUGH_GRADIENT, 1, 40, param1=10, param2=20, minRadius=0, maxRadius=0)

        # Get largest circle
        max_circle = None
        max_circle_norm = [None, None, None]
        if circles is not None:
            self.max_rad = 0
            circles = np.uint16(np.around(circles))

            for c in circles[0, :]:
                cv2.circle(seg, (c[0], c[1]), c[2], (0, 255, 0), 2)

                if c[2] > self.max_rad:
                    self.max_rad = c[2]
                    max_circle = c
                    max_circle_norm[0] = int(round(((max_circle[0] - im_centre_w) / im_centre_w) * 100.0))
                    max_circle_norm[1] = int(round(-((max_circle[1] - im_centre_h) / im_centre_h) * 100.0))
                    max_circle_norm[2] = int(round((max_circle[2] / im_centre_w) * 100.0))

                # Debug Only
                cv2.circle(output, (max_circle[0], max_circle[1]), max_circle[2], (0, 255, 0), 2)
                cv2.circle(output, (max_circle[0], max_circle[1]), 1, (0, 255, 0), 2)
                location_str = "x: " + str(max_circle_norm[0]) + "," + "y: " + str(
                    max_circle_norm[1]) + "," + "r: " + str(max_circle[2])
                text_y_offset = 18
                for i, line in enumerate(location_str.split(",")):
                    text_y = max_circle[1] - text_y_offset + i * text_y_offset
                    cv2.putText(output, line, (max_circle[0] + 5, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
                    cv2.putText(output, line, (max_circle[0] + 5, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0),
                                1)

        else:
            return None

        return max_circle_norm

    def action_space_sample(self):
        action = np.random.choice(self.action_space)
        return self.action_space.index(action)

    def get_state(self):
        state = []
        leftCamera = self.find_ball("#0000FF", 0)
        rightCamera = self.find_ball("#0000FF", 1)

        print "left", leftCamera
        print "right", rightCamera

        if not leftCamera is None:
            if leftCamera[0] < 0:
                if leftCamera[2] < 50:
                    state.append(1)
                else: state.append(2)
            else:
                if leftCamera[2] < 50:
                    state.append(3)
                else:
                    state.append(4)
        else:
            state.append(0)

        if not rightCamera is None:
            if rightCamera[0] < 0:
                if rightCamera[2] < 50:
                    state.append(1)
                else:
                    state.append(2)
            else:
                if rightCamera[2] < 50:
                    state.append(3)
                else:
                    state.append(4)
        else:
            state.append(0)

        return state

    def step(self, action_i):
        action = self.action_space[action_i]
        print "action", action

        # give the speed to go 0.5m and stop
        if action == 'PUSH':
            self.action_push()

        # turn 180 degree
        # elif action == 'STOP':
        #     self.action_stop()

        # turn 45 degree
        elif action == 'TURN_L_45':
            self.action_turn_l45()

        # turn 90 degree
        elif action == 'TURN_L_90':
            self.action_turn_l90()

        # # turn 135 degree
        # elif action == 'TURN_L_135':
        #     self.action_turn_l135()

        # turn -45 degree
        elif action == 'TURN_R_45':
            self.action_turn_r45()

        # turn -90 degree
        elif action == 'TURN_R_90':
            self.action_turn_r90()

        # # turn -135 degree
        # elif action == 'TURN_R_135':
        #     self.action_turn_r135()

        else:
            self.action_turn_180()

        new_state = self.get_state()
        # reach the goal have 1, else -1 reward
        if new_state[0] == self.goal[0] and new_state[1] == self.goal[1]:
            reward = 1
            done = True
        else:
            reward = -1
            done = False

        return new_state, reward, done

    def reset(self):
        return 0

    def action_push(self):
        start = datetime.datetime.now()

        while (self.sonar > 0.05):
            end = datetime.datetime.now()

            if (end - start).seconds > 1:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.0
                self.pub_cmd_vel.publish(self.velocity)
                break
            # time.sleep(1)
            else:
                self.velocity.twist.linear.x = 0.1
                self.velocity.twist.angular.z = 0.0
                self.pub_cmd_vel.publish(self.velocity)

    def action_stop(self):
        start = datetime.datetime.now()

        while (True):
            end = datetime.datetime.now()
            if (end - start).seconds > 0:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.0
                self.pub_cmd_vel.publish(self.velocity)
                break
            else:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.0
                self.pub_cmd_vel.publish(self.velocity)

    def action_turn_l45(self):
        start = datetime.datetime.now()

        while (True):
            end = datetime.datetime.now()
            if (end - start).seconds > 0:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.0
                self.pub_cmd_vel.publish(self.velocity)
                break
            else:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.79
                self.pub_cmd_vel.publish(self.velocity)

    def action_turn_l90(self):
        start = datetime.datetime.now()

        while (True):
            end = datetime.datetime.now()
            if (end - start).seconds > 1:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.0
                self.pub_cmd_vel.publish(self.velocity)
                break
            else:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.79
                self.pub_cmd_vel.publish(self.velocity)

    def action_turn_l135(self):
        start = datetime.datetime.now()

        while (True):
            end = datetime.datetime.now()
            if (end - start).seconds > 2:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.0
                self.pub_cmd_vel.publish(self.velocity)
                break
            else:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.79
                self.pub_cmd_vel.publish(self.velocity)

    def action_turn_r45(self):
        start = datetime.datetime.now()

        while (True):
            end = datetime.datetime.now()
            if (end - start).seconds > 0:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.0
                self.pub_cmd_vel.publish(self.velocity)
                break
            else:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = -0.79
                self.pub_cmd_vel.publish(self.velocity)

    def action_turn_r90(self):
        start = datetime.datetime.now()

        while (True):
            end = datetime.datetime.now()
            if (end - start).seconds > 1:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.0
                self.pub_cmd_vel.publish(self.velocity)
                break
            else:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = -0.79
                self.pub_cmd_vel.publish(self.velocity)

    def action_turn_r135(self):
        start = datetime.datetime.now()

        while (True):
            end = datetime.datetime.now()
            if (end - start).seconds > 2:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.0
                self.pub_cmd_vel.publish(self.velocity)
                break
            else:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = -0.79
                self.pub_cmd_vel.publish(self.velocity)

    def action_turn_180(self):
        start = datetime.datetime.now()

        while (True):
            end = datetime.datetime.now()
            if (end - start).seconds > 3:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.0
                self.pub_cmd_vel.publish(self.velocity)
                break
            else:
                self.velocity.twist.linear.x = 0.0
                self.velocity.twist.angular.z = 0.79
                self.pub_cmd_vel.publish(self.velocity)


if __name__ == "__main__":

    rospy.init_node("client_findball", anonymous=True)
    main = client_findball()
    main.loop()




