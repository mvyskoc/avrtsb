#!/usr/bin/python
# -*- coding: UTF-8 -*-
import time
import firmware
import math
import collections

from tsb_locale import *

from serial import Serial
from struct import unpack, pack
from cStringIO import StringIO

# https://docs.python.org/3/library/struct.html
TSB_CONFIRM="!"
TSB_REQUEST="?"
TSB_INFO_HEADER_SIZE=15
TSB_USER_HEADER_SIZE=3          # User header is followed with password up to end of pagesize
FLASH_PAGEWRITE_TIMEOUT=200     # Maximum time for write one page to flash - usually about 74
EMERGENCY_ERASE_TIMEOUT=60000   # Emergency erase takes a lot of time, all memories must be reprogrammed


class TSBException(Exception):
    def __init__(self, message):

        # Call the base class constructor with the parameters it needs
        super(TSBException, self).__init__(message)

class ProgressInfo(object):
    def __init__(self, total):
        self.total = total
        self.iteration = 0
        self.result = None

class DeviceInfo:
    def __init__(self):
        self.buildword = 0
        self.tsbstatus = 0
        self.signature = (0,0,0)
        self.pagesize = 0
        self.appflash = 0
        self.flashsize = 0
        self.tsbbuild = 0
        self.eepromsize = 0
        self.appjump = 0
        self.timeout = 255      #Default maximum timeout
        self.password = ""

    def parseInfoHeader(self, header):
        """
        Function parse info header received from TSB Bootloader. It returns size of header
        info header: 
        3 bytes ASCII identifier "TSB"
        2 bytes firmware date identifier
        1 byte firmware status identifier (reserved)
        3 signature bytes in the format of ATMEL signature bytes
        1 byte the Pagesize in Words (with ATtinys this may be 32, 64 or 128 Byte)
        2 bytes of available Flash memory (total free memory in bytes for Application minus Bootloader alotted memory)
        2 bytes EEPROM size
        1 byte ! CONFIRM
        """

        # For some higher baudrates can be problem with synchronisation
        # alternative header is received
        # if header[0:3] not in ("TSB", "\xd4\xd3\xc2"): - not safe
        if header[0:3] not in ("TSB"):
            print repr(header)
            raise TSBException( _("Bad info data block received !") )
        
        self.buildword = unpack("H", header[3:5])[0]
        # consider TSB firmware with new date identifier and status byte
        if self.buildword < 32768:
            self.tsbbuild = self.word2Date(self.buildword)
        else:    #old date encoding in tsb-fw (three bytes)
            self.tsbbuild = self.buildword + 65536 + 20000000
            
        self.tsbstatus = ord(header[5])
        self.signature = unpack("BBB", header[6:9])
        self.pagesize  = ord(header[9]) * 2  #Words *2 = bytes
        self.appflash  = unpack("H", header[10:12])[0] * 2 
        self.flashsize = ((self.appflash / 1024) + 1) * 1024 

        if (self.pagesize % 16) > 0:
            raise TSBException(_("Pagesize not valid - abort."))
        

        self.eepromsize = ord(header[12]) + ord(header[13])*256+1 

        # detect wheter device is ATtiny or ATmega from identifier 
        # in last byte of device info block
        # while decision for jmp/rjmp depends on memory size
        avr_jmp_identifier = {0x00: (0, 0), 0x0C: (1,0), 0xAA: (0, 1)}
        self.jmpmode, self.tinymega = avr_jmp_identifier[ord(header[15])]

        if header[-1] <> TSB_CONFIRM:
            raise TSBException(_("Error: Confirmation of header expected."))

        
    def parseUserData(self, userdata):
        self.appjump, self.timeout = unpack("HB", userdata[0:3])
        self.password = userdata[3:].strip('\xFF')

        if self.tinymega == 1:
            self.appjump = 0 #ATMega use FUSE bits for change start position
        

    def getRawUserData(self):
        """Returns raw binary data"""
        userdata = ""
        userdata += pack("HB", self.appjump, self.timeout) 
        userdata += self.password
        userdata = userdata.ljust(self.pagesize, '\xFF')        
        return userdata

    @property
    def timeout(self):
        return self._timeout
    
    @timeout.setter
    def timeout(self, value):
        value = int(value)
        if (value >= 8) and (value <= 255):
            self._timeout = value
        else:
            raise ValueError(_("Timeout factor must be in range 8..255"))
        

    @property
    def password(self):
        return self._password

    @password.setter
    def password(self, value):
        if len(value) <= self.pagesize-TSB_USER_HEADER_SIZE:
            self._password = value
        else:
            raise ValueError(_("Maximum lenght of password is %d") % (self.pagesize-TSB_USER_HEADER_SIZE,) )

    
    def tostr(self):
        fw_db = firmware.FirmwareDB()
        device_list = fw_db.sig2name(self.signature)
        device_name = ", ".join(device_list)
        
        s = []
        s.append(_("TINY SAFE BOOTLOADER"))
        s.append(_("VERSION   : %d") % (self.tsbbuild,))
        s.append(_("STATUS    : %X") % (self.tsbstatus,))
        s.append(_("SIGNATURE : %.2X %.2X %.2X") % self.signature)
        s.append(_("DEVICE    : %s") % (device_name,) )
        s.append(_("FLASH     : %d") % (self.flashsize,))
        s.append(_("APPFLASH  : %d") % (self.appflash,))
        s.append(_("PAGESIZE  : %d") % (self.pagesize,))
        s.append(_("EEPROM    : %d") % (self.eepromsize,))
        s.append(_("APPJUMP   : %.4X") % (self.appjump,))  #Userdata
        s.append(_("TIMEOUT   : %d") % (self.timeout,))    #Userdata
        return u'\n'.join(s)
        
    def word2Date(self, in_word):
        result = (in_word & 31 ) + \
                 ((in_word & 480) / 32) * 100 + \
                 ((in_word & 65024 ) / 512) * 10000 \
                  + 20000000

        return result
        

    
class TSBLoader:
    STATE_INIT=0
    STATE_ACTIVE=1
    STATE_CLOSE=2
    DTR=1
    RTS=2

    def __init__(self, serial):
        self.serial = serial
        self.reset_line = TSBLoader.DTR
        self.reset_active = 1
        self.reset_cmd = "" # Use application command for start bootloader

        self.setPassword("")
        self.one_wire = False
        self.timeout_reset = 200 #ms
        self.device_info = DeviceInfo()
        
        # Timeout 50ms is big enought for transmitt 7 characters with speed
        # 1200 B.
        # Timout cannot be shorter, because there is necessary some minimum
        # time for init TSB Bootloader protected with the password
        # Concurrently the time cannot be too long, because of the autodetection
        # if the password is necessarly
        self.serial.timeout = 0.05
        self.state = TSBLoader.STATE_INIT
    
    @property
    def reset_line():
        return self._reset_line

    @reset_line.setter
    def reset_line(self, value):
        if value not in [TSBLoader.DTR, TSBLoader.RTS]:
            raise ValueError(_("reset_line attribute can have only TSBLoader.DTR, TSBLoader.RTS value."))

        self._reset_line = value
    
    @property
    def reset_active(self):
        return self._reset_active

    @reset_active.setter
    def reset_active(self, value):
        if value not in [0, 1]:
            raise ValueError(_("reset_active attribute can have only values only 0, 1"))

    def setPassword(self, password):
        self.password = password
    
    def log(self, message):
        print(message)
        
    def sleep(self, ms):
        time.sleep(ms / 1000.0)

    def setPower(self):
        """Switch on other line than line for reset to log 1. The output
        of the pin will be cca +12V which can be use for power RS232 convertor.
        If reset by application command is used, use both RTS, DTR lines for
        power.
        """
        if self.reset_cmd:
            self.serial.setRTS(1)
            self.serial.setDTR(1)
        else:
            if self.reset_line == TSBLoader.DTR:
                self.serial.setRTS(1)
            else:
                self.serial.setDTR(1)

        self.sleep(100)

    def resetMCU(self):
        # Bootloader is started with application command
        if self.reset_cmd:
            return

        setReset = { TSBLoader.RTS : self.serial.setRTS, 
                     TSBLoader.DTR : self.serial.setDTR } [self.reset_line]
        
        activeState = {0: (0, 1), 1: (1,0)}[self.reset_active]
        setReset(activeState[0])
        self.sleep(1)
        setReset(activeState[1])
        self.sleep(self.timeout_reset)

    def sendCommand(self, astr):
        if astr == "":
            return
        
        self.serial.write(astr)
        if self.one_wire:
            echo_str = self.read( len(astr) ) 
            self.waitRespond(echo_str)
    
    
    def read(self, size=1024, timeout=None):
        """Read size of data. Finish if no data come during timeout.
        Timeout is automaticaly prolonged when receive data.
        """
        if timeout == None:
            timeout = self.serial.timeout*1000.
            
        old_timeout = self.serial.timeout
        self.serial.timeout = timeout/1000.
        data = []
        try:
            num_bytes = 0   #Number o received bytes
            while num_bytes < size:
                new_data = self.serial.read(size - num_bytes)
                num_bytes += len(new_data)
                data.append( new_data )

                #Check timeout
                if new_data == '':
                    break
        finally:
            self.serial.timeout = old_timeout

        return ''.join(data)


    def waitRespond(self, respond, timeout=None):
        """Wait than device return desired request.
           If differen answer is received or timout elapsed raise exception
        """
        rx = self.read(len(respond), timeout)
        if rx == None:
            raise TSBException(_("Timeout error - TSB does not respond"))
        elif rx <> respond:
            raise TSBException(_("Comunication error: invalid answer from TSB"))
        
        return True
        
    
    def readUserData(self):
        self.sendCommand("c")
        userdata = self.read(self.device_info.pagesize)
        if len(userdata) <> self.device_info.pagesize:
            raise TSBException(_("User data read error."))

        self.waitRespond(TSB_CONFIRM)
        return userdata
        
        
    def writeUserData(self):
        user_data = self.device_info.getRawUserData()

        self.sendCommand("C")
        self.waitRespond( TSB_REQUEST )
        self.sendCommand( TSB_CONFIRM )
        self.sendCommand( user_data )

        rx = self.read(1, FLASH_PAGEWRITE_TIMEOUT)
        if rx == TSB_CONFIRM:
           raise TSBException(_("User data write error."))

    def activateTSB(self):
        if self.reset_cmd:
            self.sendCommand(self.reset_cmd) 
            self.read() # Read confirmation from application if exist
        else:
            self.resetMCU()
        
        self.sendCommand("@@@")
        rx = self.read()
        if rx[:3] == "@@@":
            self.one_wire = True
            rx = rx[3:]     #Strip echo characters
            self.log(_("One-wire interface detected."))

        if (rx == '') and (self.password):
            self.sendCommand(self.password)
            rx = self.read()

        if rx == "":
            err_message = _("Error: Device does not respond.")
            if self.password:             
                err_message += _(" Please check your password.")
            else:
                err_message += _(" Maybe password is required.")

            raise TSBException(err_message)
        self.device_info.parseInfoHeader(rx)
        self.device_info.parseUserData(self.readUserData())
        self.state = TSBLoader.STATE_ACTIVE

    def check4SPM(self, data):
        """Check for presence of SPM instruction in the code data. SPM instruction
        is used for write into the FLASH memory."""

        #Every instructions has same size 2bytes
        opcodes = [data[i:i+2] for i in xrange(0, len(data), 2)]
        return '\xE8\x95' in opcodes
    
    def flashRead(self):
        if self.state <> TSBLoader.STATE_ACTIVE:
            self.activateTSB()

        flashdata = []
        self.sendCommand("f")

        addr = 0
        rx = "init"
        progress = ProgressInfo(self.device_info.appflash)
        while (rx <> '') and (addr < self.device_info.appflash):
            self.sendCommand(TSB_CONFIRM)
            rx = self.read(self.device_info.pagesize)
            
            if len(rx) <> self.device_info.pagesize:
                raise TSBException(_("Read flash memory page error."))
    
            addr += len(rx)
            progress.iteration += len(rx)
            flashdata.append(rx)
            yield(progress)
            
        
        if addr < self.device_info.appflash:
            raise TSBException(_("Read Error: other memory page expected."))

        self.waitRespond( TSB_CONFIRM )        
        flashdata = ''.join(flashdata)
        flashdata = flashdata.rstrip("\xFF") #Remove empty data

        progress.result = flashdata
        yield(progress)


    def flashWrite(self, data):
        pagesize = self.device_info.pagesize
        
        #Pad data to all page
        round_data = int(math.ceil(len(data) / float(pagesize)) * pagesize)
        data = data.ljust(round_data, '\xFF')
	# print "Len(data)=%d, pagesize=%d" % (len(data), pagesize)        

        if len(data) > self.device_info.appflash:
            raise TSBException(_("Error: Not enough space."))
        
        self.sendCommand("F")
        # We must wait than FLASH memory will be erased
        pages_count = self.device_info.appflash / pagesize
        self.waitRespond( TSB_REQUEST, FLASH_PAGEWRITE_TIMEOUT*pages_count) 

        progress = ProgressInfo(len(data))
        for pagenum in xrange(len(data) / pagesize):
            pagedata = data[pagenum*pagesize : (pagenum+1)*pagesize]
            self.sendCommand(TSB_CONFIRM)
            self.sendCommand(pagedata)
            # self.log(_("Flash write %.4X") % (pagenum*pagesize,))
            
            #From datasheet the maximum time for write one page is 4.5ms and
            #minimal time is 3.7 ms. 
            #Function read has timeout only for receive cca 10 characters
            #this is 100ms for 9600 bps
            rx = self.read(1, FLASH_PAGEWRITE_TIMEOUT)   #Wait up to 5ms, read 1 byte
            
            if rx == TSB_CONFIRM:
                raise TSBException(_("Error: end of appflash reached or verifying error"))
            elif rx <> TSB_REQUEST:
                raise TSBException(_("FLASH Write: Undefined error."))

            progress.iteration += pagesize
            yield(progress)



        self.sendCommand(TSB_REQUEST)
        # For AVR Tiny must wait longer time
        self.waitRespond(TSB_CONFIRM, FLASH_PAGEWRITE_TIMEOUT)

    def flashErase(self):
        data = self.device_info.flashsize * b'\xFF'
        self.flashWrite(data)

    def eepromWrite(self, data):
        pagesize = self.device_info.pagesize

        #Pad data to all page
        round_data = int(math.ceil(len(data) / float(pagesize)) * pagesize)
        data = data.ljust(round_data, '\xFF')
        
        if len(data) > self.device_info.eepromsize:
            raise TSBException(_("Error: EEPROM not enough space."))
        
        self.sendCommand("E")
        # We must wait than FLASH memory will be erased
        pages_count = self.device_info.eepromsize / pagesize

        # TODO: Verify timeout for waitRespond
        self.waitRespond( TSB_REQUEST, FLASH_PAGEWRITE_TIMEOUT*pages_count) 

        progress = ProgressInfo(len(data))
        for pagenum in xrange(len(data) / pagesize):
            pagedata = data[pagenum*pagesize : (pagenum+1)*pagesize]
            self.sendCommand(TSB_CONFIRM)
            self.sendCommand(pagedata)
            
            # From datasheet the maximum time for write one byte is 8.5 ms
            # For sure the data are realy written 10 ms timout is used
            timeout = pagesize * 10
            rx = self.read(1, timeout)
            
            if rx == TSB_CONFIRM:
                raise TSBException(_("Error: end of eeprom reached or verifying error"))
            elif rx <> TSB_REQUEST:
                raise TSBException(_("EEPROM Write: Undefined error."))

            progress.iteration += pagesize
            yield(progress)

        self.sendCommand(TSB_REQUEST)
        self.waitRespond(TSB_CONFIRM) 


    def eepromErase(self):
        data = self.device_info.eepromsize * b'\xFF'
        return self.eepromWrite(data)
        
    def eepromRead(self):
        eepromdata = []
        self.sendCommand("e")

        addr = 0
        rx = "init"
        progress = ProgressInfo(self.device_info.eepromsize)
        while (rx <> '') and (addr < self.device_info.eepromsize):
            self.sendCommand(TSB_CONFIRM)
            rx = self.read(self.device_info.pagesize)
            
            if len(rx) <> self.device_info.pagesize:
                raise TSBException(_("Read EEPROM memory page error."))
    
            addr += len(rx)
            progress.iteration += len(rx)
            eepromdata.append(rx)
            yield(progress)
        
        if addr < self.device_info.eepromsize:
            raise TSBException(_("Read Error: other EEPROM page expected."))
        
        self.sendCommand(TSB_REQUEST)
        self.waitRespond(TSB_CONFIRM)      
        eepromdata = ''.join(eepromdata)
        eepromdata = eepromdata.rstrip("\xFF") #Remove empty data

        progress.result = eepromdata
        yield(progress)
        
    
    def emergencyErase(self):
        """Delete FLASH, EEPROM and all userdate - password, timeout"""
        self.setPower()
        self.resetMCU()
        self.sendCommand("@@@")

        rx = self.read()
        if rx[:3] == "@@@":
            self.one_wire = True
            rx = rx[3:]     #Strip echo characters
            self.log(_("One-wire interface detected."))
            
        if rx:
            raise TSBException(_("TSB is accessible without password. "))
        
        self.sendCommand('\x00')
        self.waitRespond(TSB_REQUEST)  
     
        self.sendCommand(TSB_CONFIRM)
        self.waitRespond(TSB_REQUEST)
        self.sendCommand(TSB_CONFIRM)
        self.waitRespond(TSB_CONFIRM, EMERGENCY_ERASE_TIMEOUT)
  

    def close(self):
        self.sendCommand('q')
        self.resetMCU()
        self.serial.close()
        self.state = TSBLoader.STATE_CLOSE
    


