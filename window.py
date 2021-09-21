import numpy as np
import cv2
import scipy.signal as signal
import sys
from PyQt5.QtWidgets import  QWidget, QLabel, QApplication, QVBoxLayout, QGridLayout
from PyQt5.QtCore import QThread, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap
from matplotlib.figure import Figure
from matplotlib.animation import FuncAnimation
from matplotlib.backends.backend_qt5agg import (FigureCanvas, NavigationToolbar2QT as NavigationToolbar)
from matplotlib.backends.backend_qt5 import FigureCanvasQT
from threading import Thread
from queue import Queue, Empty
from time import time
from app import *

DEFAULT_FS = 30

class VideoThread(QThread):
    changePixmap = pyqtSignal(QImage)
    runs = True
    
    def __init__(self, App, Fs):
        super().__init__()
        self.App = App
        self.Fs = Fs

    def run(self):
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        # cap = cv2.VideoCapture('videos/56bpm_17_08.mp4')
        n = 0
        while cap.isOpened() and self.runs:
            ret, frame = cap.read()
            n += 1
            if n % (DEFAULT_FS//self.Fs) != 0:
                continue
            
            if ret:
                # https://stackoverflow.com/a/55468544/6622587
                try:
                    self.App.new_sample(frame)
                    x, y, width, height = self.App.bbox
                    x_bb, y_bb, w_bb, h_bb = self.App.roi
                    cv2.rectangle(frame, (int(x), int(y)), (int(x+width), int(y+height)), (0, 255, 0), 2, 1)
                    cv2.rectangle(frame, (x_bb, y_bb), (x_bb+w_bb, y_bb+h_bb), (0, 255, 0), 2)
                    frameRect =  cv2.flip(frame, 1)

                except SampleError as err:
                    frameRect =  cv2.flip(frame, 1)
                
                cv2.putText(frameRect, "Heart Rate: {:.1f} bpm".format(self.App.HeartRate), (40,40), cv2.FONT_HERSHEY_SIMPLEX, 0.75,(0,0,255),2)
                cv2.putText(frameRect, "Breathing Rate: {:.1f} bpm".format(self.App.RespRate), (40,80), cv2.FONT_HERSHEY_SIMPLEX, 0.75,(0,0,255),2)     
                rgbImage = cv2.cvtColor(frameRect, cv2.COLOR_BGR2RGB)
                h, w, ch = rgbImage.shape
                bytesPerLine = ch * w
                convertToQtFormat = QImage(rgbImage.data, w, h, bytesPerLine, QImage.Format_RGB888)
                p = convertToQtFormat.scaled(640, 480, Qt.KeepAspectRatio)
                self.changePixmap.emit(p)
                
            else:
                print('Video off')
                break
                
        cap.release()
               
    def quit(self):
        self.runs = False
        
    
class AppWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.grid_layout = QGridLayout()
        self.setLayout(self.grid_layout)
        # location and size of window that opens
        self.title = 'heart-rate'
        self.left = 100
        self.top = 100
        self.width = 1500
        self.height = 800
        self.Fs = 10
        self.n_seonds = 20
        self.t = np.linspace(start=0, stop=self.n_seonds, num=self.n_seonds*self.Fs, endpoint=False)
        
        self.initUI()

    # @pyqtSlot(QImage)
    def setImage(self, image):
        self.label.setPixmap(QPixmap.fromImage(image))
        # print('frame displayed')
        
    def WelchUpdate(self, n):
        WelchLine, = self.WelchAx.get_lines()
        
        try:
            f, pxx = self.App.WelchQueue.get_nowait()
            WelchLine.set_data(f, pxx)
            self.WelchAx.set_ylim([0, pxx.max()])
            
        except Empty:
            pass
        
        return WelchLine, 
        
    def RespUpdate(self, n):
        
        ppgLine, maxLine = self.ppgAx.get_lines()
        rriLine, = self.rriAx.get_lines()
        lombLine, = self.lombAx.get_lines()
    
        
        try:
            filtered_signal = self.App.SignalQueue.get_nowait()
            # N = len(filtered_signal)
            # currTime = N/self.App.Fs
            # t = np.linspace(start=0, stop=currTime, num=N, endpoint=False)
            ppgLine.set_data(self.t[:filtered_signal.shape[0]], filtered_signal[-self.n_seonds*self.App.Fs:])
            self.ppgAx.set_ylim([filtered_signal[-self.n_seonds*self.App.Fs:].min(), filtered_signal[-self.n_seonds*self.App.Fs:].max()])
            # self.ppgAx.set_xlim([currTime-10, currTime])
        
        # except Empty:
        #     pass
        
        # try:
            newData = self.App.RespQueue.get_nowait()
            rri = newData['rri']/self.App.Fs
            
            shift_indx = max(0, filtered_signal.shape[0]-self.n_seonds*self.App.Fs)
            peak_times = newData['peak_times'][newData['peak_times'] >= shift_indx] - shift_indx
            
            maxLine.set_data(self.t[peak_times], filtered_signal[newData['peak_times']])
            rriLine.set_data(self.t[peak_times], rri[shift_indx:])
            lombLine.set_data(newData['freqs'], newData['pgram'])
            
            self.rriAx.set_ylim([0, rri[shift_indx:].max()])
            # self.rriAx.set_xlim([currTime-20, currTime])
            
            # self.lombAx.relim()
            # self.lombAx.autoscale_view()
            
        except Empty:
            pass
        
        return ppgLine, maxLine, rriLine, lombLine
    
    def closeEvent(self, event):
        self.VideoSource.quit()
        self.VideoSource.wait()
        event.accept()
    

    def initUI(self):
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)
        # self.resize(640, 480)
        
        # create a label for live video
        self.label = QLabel(self)
        self.grid_layout.addWidget(self.label, 0, 0, 2, 2) # row, col, hight, width
        self.label.setAlignment(Qt.AlignCenter)
        self.label.resize(640, 480)
        
        # add figure for welch periodogram
        self.WelchFig = Figure(figsize=(7,2)) # width, hight
        self.WelchCanvas = FigureCanvas(self.WelchFig)
        self.grid_layout.addWidget(self.WelchCanvas, 2, 0, 1, 2)
        
        # add figure for respiratory rate
        self.RespFig = Figure(figsize=(7, 9)) #(4,9)
        self.RespCanvas = FigureCanvas(self.RespFig)
        self.grid_layout.addWidget(self.RespCanvas, 0, 2, 3, 2)
        
        
        # set up figures
        self.WelchAx = self.WelchFig.subplots()
        self.WelchAx.plot([], [])
        self.WelchAx.set_xlabel('bpm')
        self.WelchAx.set_title('welch periodogram')
        self.WelchAx.set_xlim([0, 180])
        self.WelchAx.set_ylim([0, 1.1])
        
        
        self.ppgAx, self.rriAx, self.lombAx = self.RespFig.subplots(nrows=3, ncols=1)
        self.ppgAx.plot([],[])
        self.ppgAx.plot([], [], "x")
        self.ppgAx.set_xlim([0, self.n_seonds])
        self.ppgAx.set_xlabel('time')
        self.ppgAx.set_title('ppg signal')

        self.rriAx.plot([], [])
        self.rriAx.set_xlim([0, self.n_seonds])
        self.rriAx.set_xlabel('time')
        self.rriAx.set_ylabel('rri')
        self.rriAx.set_title('rri signal')
        
        self.lombAx.plot([], [])
        self.lombAx.set_xlabel('theta [rad]')
        self.lombAx.set_title('lomb periogogram')
        
        self.WelchFig.tight_layout()
        self.RespFig.tight_layout()
        
        self.App = App(Fs=self.Fs)
        
        self.Welchani = FuncAnimation(self.RespFig, self.WelchUpdate, blit=True, interval=100) 
        self.RespAni = FuncAnimation(self.RespFig, self.RespUpdate, blit=True, interval=100)
        
        self.VideoSource = VideoThread(self.App, Fs=self.Fs)
        self.VideoSource.changePixmap.connect(self.setImage)
        self.VideoSource.finished.connect(self.close)
        self.VideoSource.start()
    
    
        self.show()
        
        
if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = AppWindow()
    sys.exit(app.exec_())