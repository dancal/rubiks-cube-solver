from tkinter import ttk
from queue import Queue
from queue import Empty
from time import sleep
from PIL import ImageTk, Image, ImageDraw
from sklearn.cluster import KMeans
from operator import itemgetter
from collections import Counter

import tkinter as tk
import threading as td
#import picamera
import pygame
import pygame.camera
import cv2
import numpy as np
import arms
import pivotpi as pp
import kociemba
import io
import json
import transitions
import logging
import sys

class QueuePubSub():
    '''
    Class that implements the notion of subscribers/publishers by using standard queues
    '''
    def __init__(self, queues):
        self.queues = queues

    def publish(self, channel, message):
        '''
        channel - An immutable key that represents the name of the channel. It can be nonexistent.
        message - The message that will be pushed to the queue that's associated to the given channel.
        '''
        if channel not in self.queues:
            self.queues[channel] = Queue()
        self.queues[channel].put(message)
    
    def subscribe(self, channel):
        '''
        channel - An immutable key that represents the name of the channel. It can be nonexistent.
        '''
        if channel not in self.queues:
            self.queues[channel] = Queue()
        return self.queues[channel]

# generic page that can be brought onto the front plane
class Page(tk.Frame):
    def __init__(self, *args, **kwargs):
        super(Page, self).__init__(*args, **kwargs)
        self.place(x=0, y=0, relwidth=1.0, relheight=1.0)

    def show(self):
        self.lift()

class Solver(Page):
    def __init__(self, *args, **kwargs):
        super(Solver, self).__init__(*args, **kwargs)
        
        self.channel = 'solver'
        self.pub = QueuePubSub(queues)
        self.sub = QueuePubSub(queues).subscribe('update')

        # Grip/Stop Functions
        self.grip_labelframe = tk.LabelFrame(self, text='Grip/Stop Functions')
        self.grip_labelframe.pack(side='left', fill=tk.Y, ipadx=2, ipady=2, padx=20, pady=20)

        # Side Grip/Stop Buttons
        self.button_names = ['Fix', 'Release', 'Stop', 'Cut Power']
        max_button_width = max(map(lambda x: len(x), self.button_names))
        self.buttons = {}
        for button_name in self.button_names:
            self.buttons[button_name] = tk.Button(self.grip_labelframe, text=button_name, width=max_button_width, height=1, command=lambda label=button_name: self.button_action(label))
            self.buttons[button_name].pack(side='top', expand=True)

        # Solver/Reader Functions
        self.solver_labelframe = tk.LabelFrame(self, text='Solver/Reader Functions')
        self.solver_labelframe.pack(side='left', fill=tk.BOTH, ipadx=2, ipady=2, padx=20, pady=20, expand=True)

        # Solver/Reader Buttons & Progress Bars 

        self.solver_labelframe.rowconfigure(0, weight=1)
        self.solver_labelframe.rowconfigure(1, weight=1)
        self.solver_labelframe.columnconfigure(0, weight=1)
        self.solver_labelframe.columnconfigure(1, weight=3)
        self.solver_labelframe.columnconfigure(2, weight=1)

        new_buttons = ['Read Cube', 'Solve Cube']
        max_button_width = max(map(lambda x: len(x), new_buttons))
        for idx, button_name in enumerate(new_buttons):
            self.buttons[button_name] = tk.Button(self.solver_labelframe, text=button_name, width=max_button_width, height=1, command=lambda label=button_name: self.button_action(label))
            self.buttons[button_name].grid(row=idx, column=0, padx=20, pady=20, sticky='nw')

        self.progress_bars = {}
        self.bar_names = new_buttons
        for idx, bar_name in enumerate(self.bar_names):
            self.progress_bars[bar_name] = ttk.Progressbar(self.solver_labelframe, orient='horizontal', length=100, mode='determinate')
            self.progress_bars[bar_name].grid(row=idx, column=1, padx=20, pady=20, sticky='nwe')

        self.progress_labels = {}
        self.label_names = new_buttons
        max_button_width = max(map(lambda x: len(x), self.label_names))
        for idx, label_name in enumerate(self.label_names):
            self.progress_labels[label_name] = tk.Label(self.solver_labelframe, text='0%', height=1, width=max_button_width, justify=tk.LEFT, anchor=tk.W)
            self.progress_labels[label_name].grid(row=idx, column=2, padx=20, pady=20, sticky='nw')

        self.button_names += new_buttons
        self.buttons['Solve Cube'].config(state='disabled')

        self.after(50, self.refresh_page)

    def button_action(self, label):
        self.pub.publish(self.channel, label)

    def refresh_page(self):
        try:
            # block or disable the solve button
            update = self.sub.get(block=False)
            if update['solve_button_locked'] is True:
                state = 'disabled'
            else:
                state = 'normal'
            if self.buttons['Solve Cube']['state'] != state:
                self.buttons['Solve Cube'].config(state=state)
                logger.info('{} \'Solve Cube\' button'.format(state))
            
            # update both progress bars
            read_progress_bar = update['read_status']
            solve_progress_bar = update['solve_status']
            self.progress_bars['Read Cube']['value'] = read_progress_bar
            self.progress_bars['Solve Cube']['value'] = solve_progress_bar

            # update both labels of both progress bars
            self.progress_labels['Read Cube']['text'] = '{}%'.format(int(read_progress_bar))
            self.progress_labels['Solve Cube']['text'] = '{}%'.format(int(solve_progress_bar))

        except Empty:
            pass
        finally:
            self.after(50, self.refresh_page)

class Camera(Page):
    def __init__(self, *args, **kwargs):
        super(Camera, self).__init__(*args, **kwargs)
        
        self.channel = 'config'
        self.pub = QueuePubSub(queues)

        # left big frame
        self.entries_frame = tk.LabelFrame(self, text='Interest Zones')
        self.entries_frame.pack(side='left', fill=tk.Y, ipadx=2, ipady=2, padx=20, pady=20)

        # configure layout of labels and buttons in the left frame
        self.entries_frame.rowconfigure(0, weight=1)
        self.entries_frame.rowconfigure(1, weight=1)
        self.entries_frame.rowconfigure(2, weight=1)
        self.entries_frame.rowconfigure(3, weight=1)
        self.entries_frame.rowconfigure(4, weight=1)
        self.entries_frame.columnconfigure(0, weight=1)
        self.entries_frame.columnconfigure(1, weight=1)

        # and setup the labels and the buttons in the left frame
        self.labels = {}
        self.entries = {}
        self.entry_values = {}
        self.label_names = ['X Offset (px)', 'Y Offset (px)', 'Size (px)', 'Pad (px)']
        max_button_width = max(map(lambda x: len(x), self.label_names))
        for idx, text in enumerate(self.label_names):
            self.labels[text] = tk.Label(self.entries_frame, text=text, height=1, width=max_button_width, justify='right', anchor=tk.W)
            self.labels[text].grid(row=idx, column=0, padx=20, pady=10)

            self.entry_values[text] = tk.IntVar()
            self.entries[text] = tk.Entry(self.entries_frame, justify='left', width=5, textvariable=self.entry_values[text])
            self.entries[text].grid(row=idx, column=1, padx=20, pady=10)

        # create the capture button
        self.button_frame = tk.Frame(self.entries_frame)
        self.button_frame.grid(row=4, column=0, columnspan=2)
        self.button_names = ['Load', 'Save', 'Preview']
        max_width = max(map(lambda x: len(x), self.button_names))
        self.buttons = {}
        for btn_name in self.button_names:
            self.buttons[btn_name] = tk.Button(self.button_frame, text=btn_name, width=max_width, command=lambda label=btn_name: self.button_action(label))
            self.buttons[btn_name].pack(side='left', expand=True, padx=2, pady=2)
        # self.capture_button = tk.Button(self.entries_frame, text='Get Preview', command=self.button_pressed)
        # self.capture_button.grid(row=4, column=0, columnspan=2)

        # right big frame (actually label) that includes the preview image from the camera
        self.images = tk.Label(self, text='No captured image', bd=2, relief=tk.RIDGE)
        self.images.pack(side='left', fill=tk.BOTH, ipadx=2, ipady=2, padx=20, pady=20, expand=True)

        # load the config file on app launch
        self.button_action(self.button_names[0])

    
    # every time the get preview button is pressed
    def button_action(self, label):
        if label in self.button_names[:2]:
            # load config file
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)

                # load config file into this class
                if label == self.button_names[0]:
                    for key in self.label_names:
                        val = config['camera'][key]
                        self.entry_values[key].set(val)
            except:
                logger.warning('config file can\'t be loaded because it doesn\'t exist')
                config = {}

            # save config file
            if label == self.button_names[1]:
                config['camera'] = {}
                for key in self.label_names:
                    config['camera'][key] = self.entry_values[key].get()
                try:
                    with open(config_file, 'w') as f:
                        json.dump(config, f, indent=4, sort_keys=True)
                except:
                    logger.warning('failed saving the config file')

            self.pub.publish(self.channel, config)

        # if we have to get a preview
        if label == self.button_names[2]:
            xoff = self.entry_values['X Offset (px)'].get()
            yoff = self.entry_values['Y Offset (px)'].get()
            dim = self.entry_values['Size (px)'].get()
            pad = self.entry_values['Pad (px)'].get()

            img = camera.get_overlayed_processed_image(xoff, yoff, dim, pad)
            img = Image.fromarray(img)
            out = ImageTk.PhotoImage(img)

            self.images.configure(image=out)
            self.images.image = out

class Arms(Page):
    def __init__(self, *args, **kwargs):
        super(Arms, self).__init__(*args, **kwargs)
        # label = tk.Label(self, text='This is page arms', bg='green', justify=tk.CENTER)
        # label.pack(side='top', fill='both', expand=True)

        self.channel_cfg = 'config'
        self.channel_play = 'arms_play'
        self.channel_solver = 'solver'
        self.pub = QueuePubSub(queues)

        self.arms = ['Arm 1', 'Arm 2', 'Arm 3', 'Arm 4']
        self.arm_labels = {}

        # just labels for the servos
        self.low_servo_labels = []
        self.high_servo_labels = []

        # integer entries for the servo limits
        self.low_servo_entries = []
        self.high_servo_entries = []
        self.low_servo_vals = []
        self.high_servo_vals = []

        # and the actual sliders for testing
        self.servo_sliders = []

        for idx, arm in enumerate(self.arms):
            self.arm_labels[arm] = tk.LabelFrame(self, text=arm)
            self.arm_labels[arm].pack(side='top', fill=tk.BOTH, expand=True, ipadx=10, ipady=2, padx=15, pady=5)
            
            for i in range(2):
                servo_idx = 2 * idx + i
                if servo_idx % 2 == 0:
                    t1 = 'Pos'
                else:
                    t1 = 'Rot'
                # low positioned labels
                self.low_servo_labels.append(tk.Label(self.arm_labels[arm], text='S{} '.format(servo_idx + 1) + 'Low ' + t1))
                self.low_servo_labels[-1].pack(side='left', fill=tk.BOTH, padx=2)
                # low positioned entries
                self.low_servo_vals.append(tk.IntVar())
                self.low_servo_entries.append(tk.Entry(self.arm_labels[arm], justify='left', width=5, textvariable=self.low_servo_vals[-1]))
                self.low_servo_entries[-1].pack(side='left', fill=tk.X, padx=2)

                # high positioned labels
                self.high_servo_labels.append(tk.Label(self.arm_labels[arm], text='S{} '.format(servo_idx + 1) + 'High ' + t1))
                self.high_servo_labels[-1].pack(side='left', fill=tk.BOTH, padx=2)
                # high positioned entries
                self.high_servo_vals.append(tk.IntVar())
                self.high_servo_entries.append(tk.Entry(self.arm_labels[arm], justify='left', width=5, textvariable=self.high_servo_vals[-1]))
                self.high_servo_entries[-1].pack(side='left', fill=tk.X, padx=2)

                # slider
                self.servo_sliders.append(tk.Scale(self.arm_labels[arm], from_=0, to=100, orient=tk.HORIZONTAL, showvalue=0, command=lambda val, s=servo_idx: self.scale(s, val)))
                self.servo_sliders[-1].pack(side='left', fill=tk.X, expand=True, padx=3)

        self.button_frame = tk.LabelFrame(self, text='Actions')
        self.button_frame.pack(side='top', fill=tk.BOTH, expand=True, ipadx=10, ipady=2, padx=15, pady=5)
        self.button_names = ['Load Config', 'Save Config', 'Cut Power']
        max_width = max(map(lambda x: len(x), self.button_names))
        self.buttons = {}
        for btn_name in self.button_names:
            self.buttons[btn_name] = tk.Button(self.button_frame, text=btn_name, width=max_width, command=lambda label=btn_name: self.button_action(label))
            self.buttons[btn_name].pack(side='left', expand=True)
        
        # load config values on app launch
        self.button_action(self.button_names[0])

    def scale(self, servo, value):
        self.pub.publish(self.channel_play, [servo, value])

    def button_action(self, label):
        # load/save config file
        if label in self.button_names[:2]:
            # load config file
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)

                # load config file into this class
                if label == self.button_names[0]:
                    for idx, _ in enumerate(self.arms * 2):
                        arm = config['servos']['s{}'.format(idx + 1)]
                        self.low_servo_vals[idx].set(arm['low'])
                        self.high_servo_vals[idx].set(arm['high'])
            except:
                logger.warning('config file can\'t be loaded because it doesn\'t exist')
                config = {}

            # save config file
            if label == self.button_names[1]:
                config['servos'] = {}
                for idx, _ in enumerate(self.arms * 2):
                    arm = {
                        'low': self.low_servo_vals[idx].get(),
                        'high': self.high_servo_vals[idx].get()
                    }
                    config['servos']['s{}'.format(idx + 1)] = arm
                try:
                    with open(config_file, 'w') as f:
                        json.dump(config, f, indent=4, sort_keys=True)
                except:
                    logger.warning('failed saving the config file')

            self.pub.publish(self.channel_cfg, config)

        elif label == self.button_names[2]:
            self.pub.publish(self.channel_solver, label)
            

class MainView(tk.Tk):
    def __init__(self, size, name):

        # initialize root window and shit
        super(MainView, self).__init__()
        self.geometry(size)
        self.title(name)
        self.resizable(False, False)
        # initialize master-root window
        window = tk.Frame(self, bd=2)
        window.pack(side='top', fill=tk.BOTH, expand=True)
        
        # create the 2 frames within the window container
        button_navigator = tk.Frame(window, bd=2, relief=tk.FLAT)
        pages = tk.Frame(window, bd=2, relief=tk.RIDGE)

        # define the frames' dimensions
        window.rowconfigure(0, weight=19)
        window.rowconfigure(1, weight=1, minsize=25)
        window.columnconfigure(0, weight=1)

        # and organize them by rows/columns
        pages.grid(row=0, column=0, sticky='nswe', padx=2, pady=2)
        button_navigator.grid(row=1, column=0, sticky='nswe', padx=2, pady=2)

        # create the 3 pages 
        self.frames = {}
        for F in (Solver, Camera, Arms):
            page_name = F.__name__
            frame = F(pages)
            self.frames[page_name] = frame

        # and link the pages to their respective buttons
        for label in ('Solver', 'Camera', 'Arms'):
            button = tk.Button(button_navigator, text=label, command=self.frames[label].show)
            button.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=3)

        # and show the default page
        self.frames['Solver'].show()

class PiCameraPhotos():
    def __init__(self):
        # initialize camera with a set of predefined values
        """
        self.camera = picamera.PiCamera()
        # self.camera.resolution = (1920, 1080)
        # self.camera.framerate = 30
        # self.camera.sensor_mode = 1
        # self.camera.rotation = 180
        # self.camera.shutter_speed = 32000
        # self.camera.brightness = 60
        # self.camera.exposure_mode = 'off'
        self.camera.rotation = 180
        self.camera.awb_mode = 'off'
        self.camera.awb_gains = 1.63
        
        # also initialize the container for the image
        self.stream = io.BytesIO() 
        """

        pygame.camera.init()
        pygame.camera.list_cameras()
        self.camera	= pygame.camera.Camera('/dev/video0', (800, 600))
        self.camera.start()

    def capture(self):
        """
        Captures an image from the Pi Camera.
        :return: A Pillow.Image image.
        """
        img = self.camera.get_image()
        # return Image.open(img)

        pygame.image.save(img, '/dev/shm/rubiks.jpg')
        return Image.open('/dev/shm/rubiks.jpg')
		
    def get_camera_roi(self, xoff, yoff, dim, pad):
        """
        Computes the Regions-of-Interest for the cube's labels.
        :param xoff: Offset in pixels on the X axis.
        :param yoff: Offset in pixels on the Y axis.
        :param dim: Dimension of the squared box that sits on top of a label. Measured in pixels.
        :param pad: Pad distance between squared boxes.
        :return: A 3x3 list with each element containing a dictionary with 'x', 'y', 'dim' labels
        representing the top left corner of a label and the dimension of that squared box.
        """
        cols_count = rows_count = 3
        roi = [[0 for x in range(cols_count)] for x in range(rows_count)]
        for row in range(rows_count):
            for col in range(cols_count):
                roi[row][col] = {
                    'x': xoff + col * (dim + pad),
                    'y': yoff + row * (dim + pad),
                    'dim': dim
                }
        return roi

    def get_processed_image(self):
        """
        Captures an image and processes it. It applies the CLAHE algorithm,
        a Gaussian blur and an increase of the image's saturation by a fixed amount.
        :return: RGB image as numpy array.
        """

        # convert the captured image to a numpy array
        img = self.capture()
        img = np.asarray(img)

        # # apply CLAHE algorithm to increase contrast in
        # # low lighting areas of the image and preserve
        # # the contrast in good ones
        # img = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        # clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(6, 6))
        # img[:, :, 0] = clahe.apply(img[:, :, 0])
        # img = cv2.cvtColor(img, cv2.COLOR_LAB2RGB)

        # apply a Gaussian blur
        img = cv2.GaussianBlur(img, (7, 7), sigmaX=0.0)

        # # increase saturation by satadj amount
        # satadj = 1.0
        # imghsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
        # (h, s, v) = cv2.split(imghsv.astype(np.float32))
        # s = s * satadj
        # s = np.clip(s, 0, 255)
        # imghsv = cv2.merge((h, s, v))
        # imghsv = imghsv.astype(dtype=np.uint8)
        # imgsat = cv2.cvtColor(imghsv, cv2.COLOR_HSV2RGB)
        # img = imgsat

        return img

    def get_overlayed_processed_image(self, xoff, yoff, dim, pad):
        """
        Captures an image, processes it and draws the Regions-of-Interest
        on the image itself.
        It needs the `xoff`, `yoff`, `dim` and `pad` arguments when calling get_camera_roi
        method.
        :return: RGB image as numpy array.
        """
        img = self.get_processed_image()
        roi = self.get_camera_roi(xoff, yoff, dim, pad)

        for rectangles in roi:
            for rectangle in rectangles:
                x = rectangle['x']
                y = rectangle['y']
                dim = rectangle['dim']
                cv2.rectangle(img, (x, y), (x+dim, y+dim), (255,255,255), thickness=2)

        return img

    def get_camera_color_patches(self, xoff, yoff, dim, pad):
        """
        Captures an image, processes it and selects the Regions-of-Interest, after which
        they get averaged and a array of 3x3x3 elements are returned: 3x3 labels by 3
        channels. Each pixel needs 3 channels.
        It needs the `xoff`, `yoff`, `dim` and `pad` arguments when calling get_camera_roi
        method.
        :return: A LAB image as a 3x3x3 numpy array for all 9 labels of a cube's face.
        """
        img = self.get_processed_image()
        img = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        roi = self.get_camera_roi(xoff, yoff, dim, pad)
        color_patches = np.zeros(shape=(3, 3, 3), dtype=np.uint8)

        for row in range(3):
            for col in range(3):
                cropper = roi[row][col]
                x = cropper['x']
                y = cropper['y']
                dim = cropper['dim']
                temp = img[y:y+dim, x:x+dim]
                temp = temp.reshape(temp.shape[0] * temp.shape[1], temp.shape[2])
                pixel = temp.mean(axis=0)
                color_patches[row, col, :] = [int(x) for x in pixel]

        return color_patches

class RubiksSolver():
    def __init__(self, channel):
        """
        Initialize a model object for the FSM.
        :param channel: The channel to which commands have to be published.
        """
        self.pub = QueuePubSub(queues)
        self.channel = channel
        self.thread_stopper = td.Event()
        self.thread = None
        self.cubesolution = None

    def __execute_command(self, command):
        """
        Execute a command on the PivotPi.
        :param command: A dictionary containing the 'time', 'servo' and
        'position' keys representing the time needed for the command to get
        executed, the servo onto which the action has to be applied (starts from 1)
        and the position in degrees at which the servo has to move to.
        :return: True if it succeeded or False otherwise.
        """
        time = command['time']
        # we know the servo number is the 2nd element of the string
        servo = int(command['servo'][1]) - 1
        position = command['position']

        # move the servo
        try:
            pivotpi.angle(servo, position)
            sleep(time)
        except:
            return False

        return True

    def __instantiate_arms(self, config, mode):
        """
        Initialize the robot's arms either in released or fixed mode.
        :param config: The configuration dictionary as it comes from the GUI app.
        :param mode: 'fix' or 'release'.
        :return: A list of 4 elements with instances of the arms.Arm class.
        """
        robot_arms = []
        servos = config['servos']

        if mode == 'fix':
            pos = 'low'
        elif mode == 'release':
            pos = 'high'
        else:
            return None

        keys = list(servos.keys())
        keys.sort()

        # because there are 4 arms
        for i in range(4):
            linear_servo = keys[2 * i]
            rotational_servo = keys[2 * i + 1]
            linear_cfg = servos[linear_servo]
            rotational_cfg = servos[rotational_servo]
            robot_arms.append(
                arms.Arm(linear_servo, rotational_servo,
                         linear_cfg['low'], linear_cfg['high'],
                         rotational_cfg['low'], rotational_cfg['high'],
                         linear_cfg[pos], rotational_cfg['low'],
                         rotation_speed=0.004, command_delay=0.05)
            )

        return robot_arms

    def __instantiate_arms_in_release_mode(self, config):
        """
        Same thing as calling __instantiate_arms with mode set to 'release'.
        :param config: The configuration dictionary as it comes from the GUI app.
        :return: A list of 4 elements with instances of the arms.Arm class.
        """
        return self.__instantiate_arms(config, mode='release')

    def __instantiate_arms_in_fix_mode(self, config):
        """
        Same thing as calling __instantiate_arms with mode set to 'fix'.
        :param config: The configuration dictionary as it comes from the GUI app.
        :return: A list of 4 elements with instances of the arms.Arm class.
        """
        return self.__instantiate_arms(config, mode='fix')

    def __generate_handwritten_solution_from_cube_state(self, cube_centers, rubiks_labels):
        """
        Generate movement solution for the robot's arms. This method returns the sequence of
        steps required for the robot to solve the cube.

        :param cube_centers: A 6-element list containing the numeric labels for each face's center.
        :param rubiks_labels: Flattened Rubik's cube labels in the order expected by the muodov/kociemba library.
        These labels are numeric.
        :return:
        """
        # generate dictionary to map between center labels as
        # digits to labels as a handwritten notation: URFDLB
        kociembas_input_labels = {}
        for center, label in zip(cube_centers, 'U R F D L B'.split()):
            kociembas_input_labels[center] = label

        # generate the cube's state as a list of strings of 6x9 labels
        cubestate = [kociembas_input_labels[label] for label in rubiks_labels]
        cubestate = ''.join(cubestate)

        # generate the solution for the given cube's state
        solved = kociemba.solve(cubestate)
        solved = solved.split(' ')

        return solved

    def unblock_solve(self, event):
        """
        Unblock the solve button in the GUI app.
        :param event: Unnecessary.
        :return: Nothing.
        """
        logger.debug('unblock solve button')
        self.pub.publish(self.channel, {
            'solve_button_locked': False,
            'read_status': 0,
            'solve_status': 0

        })

    def is_finished(self, event):
        """
        Checks if any thread that runs in the background has finished (
        either for solving or reading the cube).
        :param event: Not necessary.
        :return: Whether the thread is still running or not.
        """
        return self.thread_stopper.is_set()

    def block_solve(self, event):
        """
        Blocks the solve button and stops the arms' motors.
        :param event: Not necessary here.
        :return: Nothing.
        """
        logger.debug('block solve button')
        if self.thread != None and not self.thread_stopper.is_set():
            self.thread_stopper.set()
            self.thread.join()
        hard = event.kwargs.get('hard')
        if hard is True:
            # cut the power from the servos
            logger.debug('hard stop servos')
        else:
            # just stop the motors but don't cut the power
            logger.debug('soft stop servos')
        # and publish what's necessary for the GUI
        self.pub.publish(self.channel, {
            'solve_button_locked': True,
            'read_status': 0,
            'solve_status': 0
        })

    def readcube(self, event):
        """
        Spins up the thread for readcube_thread method.
        :param event: Is a dictionary that contains the arm configs as received from the GUI app.
        :return: Nothing.
        """
        logger.debug('start thread for reading the cube')
        self.config = event.kwargs.get('config')
        self.thread_stopper.clear()
        self.thread = td.Thread(target=self.readcube_thread)
        self.thread.start()

    def readcube_thread(self):
        """
        Method which scans the cube's surface.
        :return: Nothing.
        """
        logger.debug('reading cube')
        self.pub.publish(self.channel, {
            'solve_button_locked': False,
            'read_status': 0,
            'solve_status': 0
        })

        # instantiate arms and reposition
        robot_arms = self.__instantiate_arms_in_release_mode(self.config)
        generator = arms.ArmSolutionGenerator(*robot_arms)
        generator.reposition_arms(delay=1.0)
        generator.fix()

        # generate the sequence of motions and actions to
        # scan the rubik's cube
        generator = arms.ArmSolutionGenerator(*robot_arms)
        generator.append_command('take photo')
        generator.rotate_cube_towards_right()
        generator.append_command('take photo')
        generator.rotate_cube_towards_right()
        generator.append_command('take photo')
        generator.rotate_cube_towards_right()
        generator.append_command('take photo')
        generator.rotate_cube_upwards()
        generator.append_command('take photo')
        generator.rotate_cube_upwards()
        generator.rotate_cube_upwards()
        generator.append_command('take photo')

        # save the generator for solving the cube
        self.generator = generator

        # get the generated sequence
        sequence = generator.arms_solution

        # execute the generated sequence of motions
        # while at the same time capturing the photos of the cube
        numeric_faces = []
        length = len(sequence)
        # pic_counter = 0
        for idx, step in enumerate(sequence):
            # quit process if it has been stopped
            if self.thread_stopper.is_set():
                return
            # take photos or rotate the bloody cube
            if step:
                logger.debug('Execute \'' + str(step) + '\'')
                if step == 'take photo':
                    xoff = self.config['camera']['X Offset (px)']
                    yoff = self.config['camera']['Y Offset (px)']
                    dim = self.config['camera']['Size (px)']
                    pad = self.config['camera']['Pad (px)']
                    lab_face = camera.get_camera_color_patches(xoff, yoff, dim, pad)
                    numeric_faces.append(lab_face)

                    # enable this if you want to have the cube's pics saved
                    # img = camera.get_processed_image()
                    # img = Image.fromarray(img)
                    # img.save("{}.png".format(pic_counter))
                    # pic_counter += 1
                else:
                    success = self.__execute_command(step)
            # update the progress bar
            self.pub.publish(self.channel, {
                'solve_button_locked': False,
                'read_status': 100 * (idx + 1) / length,
                'solve_status': 0
            })

        # reorder faces based on the current position of the rubik's cube
        # after it has been rotated multiple times to scan its labels
        # and also map the labels so that they match the pattern imposed
        # by muodov/kociemba's library: URFDLB.
        reoriented_faces = [
            np.rot90(numeric_faces[1], k=2),  # rotate by 180 degrees
            np.rot90(numeric_faces[0], k=1, axes=(0, 1)),  # rotate by 90 degrees anticlockwise
            numeric_faces[5], # keep the same orientation
            numeric_faces[3], # keep the same orientation
            np.rot90(numeric_faces[2], k=1, axes=(1, 0)),  # rotate by 90 degrees clockwise
            np.rot90(numeric_faces[4], k=2)  # rotate by 180 degrees
        ]

        # reshape the little bastard faces to be "fittable" by the KMeans algorithm
        for i in range(6):
            reoriented_faces[i] = reoriented_faces[i].reshape((3*3, 3))

        # clusterize the labels on the rubik's cube
        rubiks_colors = np.concatenate(reoriented_faces, axis=0)
        kmeans = KMeans(n_clusters=6, n_init=50).fit(rubiks_colors)
        rubiks_labels = kmeans.labels_

        # get the cube's centers as numeric values
        center_indexes = [4, 13, 22, 31, 40, 49] # cube centers when flattened
        cube_centers = list(itemgetter(*center_indexes)(rubiks_labels))
        labels_of_each_color = dict(Counter(rubiks_labels))

        # calculate how many different colors there are on each face
        # required for detecting if the cube is already solved
        face_color_labels = [list(set(rubiks_labels[i * 9: (i + 1) * 9])) for i in range(6)]
        face_labels_count = [len(x) for x in face_color_labels]

        # check if each center has a different label
        if len(set(cube_centers)) != 6:
            self.cubesolution = None
            logger.warning('didn\'t find the 6 cube centers of the rubik\'s cube. Cube centers are {}'.format(cube_centers))
            # logger.debug(rubiks_labels.reshape((6,3,3)))

        # check if there's an equal number of labels for each color of all six of them
        elif len(set(labels_of_each_color.values())) != 1:
            self.cubesolution = None
            logger.warning('found a different number of labels for some centers off the cube. The number of labels that were detected are {}'.format(labels_of_each_color))
            # logger.debug(rubiks_labels.reshape((6,3,3)))

        # check if the cube is already solved
        elif len(set(face_labels_count)) == 1:
            self.cubesolution = []
            logger.warning('the cube is already solved')

        # if all tests from the above are a go then go and solve the cube
        else:
            self.cubesolution = self.__generate_handwritten_solution_from_cube_state(cube_centers, rubiks_labels)
            logger.debug(self.cubesolution)

        # mark the end of the thread
        self.thread_stopper.set()

        # if the cube is already solved, then
        # bring the FSM into its rest state
        if self.cubesolution == []:
            self.stop(hard=False)

    def solvecube(self, event):
        """
        Spins up the thread for solvecube_thread method.
        :param event: Not necessary.
        :return: Nothing.
        """
        logger.debug('start thread for solving the cube')
        self.thread_stopper.clear()
        self.thread = td.Thread(target=self.solvecube_thread)
        self.thread.start()

    def solvecube_thread(self):
        """
        Solve's the Rubik's cube. Uses the cubesolution attribute
        to get its steps.
        :return: Nothing.
        """
        logger.debug('solving cube')
        self.pub.publish(self.channel, {
            'solve_button_locked': False,
            'read_status': 100,
            'solve_status': 0
        })

        # stop this thread if there's no solution
        if not self.cubesolution:
            self.thread_stopper.set()
            return

        # otherwise instantiate the arms and reposition (and eventually solve the cube)
        # robot_arms = self.__instantiate_arms_in_fix_mode(self.config)
        # generator = arms.ArmSolutionGenerator(*robot_arms)
        generator = self.generator
        generator.reset_arm_solution()
        generator.solution(self.cubesolution)

        # get the generated sequence
        sequence = generator.arms_solution

        # solve the rubik's cube by actuating the arms
        length = len(sequence)
        for idx, step in enumerate(sequence):
            if self.thread_stopper.is_set():
                return
            if step:
                logger.debug('Execute \'' + str(step) + '\'')
                success = self.__execute_command(step)
            self.pub.publish(self.channel, {
                'solve_button_locked': False,
                'read_status': 100,
                'solve_status':  100 * (idx + 1) / length
            })
            idx += 1

        self.thread_stopper.set()

    def process_command(self, event):
        """
        Process the commands for reflexive transitions into the rest state.
        :param event: Must have 'config' and 'type' keys. Can have 'action',
        'servo' and 'pos' keys.
        :return: Nothing.
        """
        config = event.kwargs.get('config')
        cmd_type = event.kwargs.get('type')
        if cmd_type == 'system':
            action = event.kwargs.get('action')

            # instantiate arms and reposition
            robot_arms = self.__instantiate_arms_in_release_mode(config)
            generator = arms.ArmSolutionGenerator(*robot_arms)
            generator.reposition_arms(delay=1.0)

            if action == 'fix':
                generator.fix()
            elif action == 'release':
                generator.release()

            sequence = generator.arms_solution
            for step in sequence:
                if step:
                    logger.debug(step)
                    success = self.__execute_command(step)

        elif cmd_type == 'servo':
            servo = int(event.kwargs.get('servo'))
            pos_percent = int(event.kwargs.get('pos'))
            servo_name = 's{}'.format(servo + 1)
            low = config['servos'][servo_name]['low']
            high = config['servos'][servo_name]['high']
            pos = low + (high - low) * pos_percent / 100
            pivotpi.angle(servo, pos)
            

if __name__ == '__main__':
    hldr = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter('%(asctime)s %(levelname)2s %(name)s | %(message)s')
    hldr.setLevel(logging.DEBUG)
    hldr.setFormatter(fmt)

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(hldr)

    logger_trans = logging.getLogger('transitions')
    logger_trans.setLevel(logging.INFO)
    logger_trans.addHandler(hldr)

    queues = {}
    config_file = 'config.json'
    camera = PiCameraPhotos()
    stop_event = td.Event()

    pivotpi = pp.PivotPi()


    def fsm_runner():
        # sub/pub channels in and from the GUI app
        subs_channels = ['solver', 'config', 'arms_play']
        pubs_channels = ['update']
        subs = [QueuePubSub(queues).subscribe(channel) for channel in subs_channels]

        # config for arms
        config = {}
        
        # finite state machine 
        rubiks = RubiksSolver(pubs_channels[0])
        machine = transitions.Machine(
            model=rubiks,
            states=['rest', 'reading', 'solving'],
            initial='rest',
            send_event=True
        )
        # FSM's transitions
        machine.add_transition(trigger='read', source='rest', dest='reading', after='readcube')
        machine.on_enter_reading('unblock_solve')
        machine.add_transition(trigger='solve', source='reading', dest='solving', conditions='is_finished', after='solvecube')
        machine.add_transition(trigger='success', source='solving', dest='rest', conditions='is_finished', after='block_solve')
        machine.add_transition(trigger='stop', source='*', dest='rest', after='block_solve')
        machine.add_transition(trigger='command', source='rest', dest='=', after='process_command')

        while not stop_event.is_set():
            for sub, channel in zip(subs, subs_channels):
                try:
                    message = sub.get(block=False)
                    if channel == 'config':
                        if rubiks.state == 'rest':
                            config = message
                            logger.info('save/load button pressed (update solver configs)')
                        else:
                            logger.info('save/load button pressed, but not updating the solver configs because it\'s in rest state')
                    elif channel == 'solver':
                        msg = message.lower()
                        if 'read cube' == msg:
                            rubiks.read(config=config) # change state here
                        elif 'solve cube' == msg:
                            rubiks.solve() # change state here
                        elif 'stop' == msg:
                            rubiks.stop(hard=False) # change state here
                        elif 'cut power' == msg:
                            rubiks.stop(hard=True) # change state here
                        elif 'fix' == msg:
                            rubiks.command(config=config, type='system', action='fix') # reflexive state here
                        elif 'release' == msg:
                            rubiks.command( config=config, type='system', action='release') # reflexive state here
                        logger.info('\'' + msg + '\' button pressed')
                    elif channel == 'arms_play':
                        servo, pos = message
                        rubiks.command(config=config, type='servo', servo=servo, pos=pos) # change state here
                        logger.info('rotate servo {} to position {}'.format(servo, pos))

                except Empty:
                    pass
                except transitions.MachineError as error:
                    logger.warning(error)

                # transition to rest from the solving state if the cube got solved
                if rubiks.state == 'solving' and rubiks.is_finished(None):
                    rubiks.success()
                    logger.info('the rubik\'s cube got solved')

            sleep(0.001)
    
    fsm_thread = td.Thread(target=fsm_runner, name='FSM Runner')
    fsm_thread.start()

    try:
        app = MainView(size='800x400', name='WASAMD - Rubik\'s Cube Solver')
        app.mainloop()
    except Exception as e:
        logger.exception(e)
    finally:
        stop_event.set()
