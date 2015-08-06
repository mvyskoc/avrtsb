#!/usr/bin/python
# -*- coding: UTF-8 -*-
import time
from tsb_locale import *

from serial import Serial
from struct import unpack, pack
from cStringIO import StringIO

# https://docs.python.org/3/library/struct.html
TSB_CONFIRM="!"
TSB_REQUEST="?"
TSB_INFO_HEADER_SIZE=15
TSB_USER_HEADER_SIZE=3          #User header is followed with password up to end of pagesize
FLASH_PAGEWRITE_TIMEOUT=200     #Maximum time for write one page to flash - usually about 74
EMERGENCY_ERASE_TIMEOUT=60000   #Emergency erase takes a lot of time, all memories must be reprogrammed


class TSBException(Exception):
    def __init__(self, message):

        # Call the base class constructor with the parameters it needs
        super(TSBException, self).__init__(message)

     
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
        if header[0:3].lower() <> "tsb":
            print header
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
        self.password = userdata[3:]

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

    
    def __str__(self):
        s = []
        s.append(_("TINY SAFE BOOTLOADER"))
        s.append(_("VERSION   : %d") % (self.tsbbuild,))
        s.append(_("STATUS    : %X") % (self.tsbstatus,))
        s.append(_("SIGNATURE : %.2X %.2X %.2X") % self.signature)
        s.append(_("DEVICE    : %s") % (AVR_SIG2NAME.get(self.signature, (_("UNKNOWN"),_("UNKNOWN")))[1],) )
        s.append(_("FLASH     : %d") % (self.flashsize,))
        s.append(_("APPFLASH  : %d") % (self.appflash,))
        s.append(_("PAGESIZE  : %d") % (self.pagesize,))
        s.append(_("EEPROM    : %d") % (self.eepromsize,))
        s.append(_("APPJUMP   : %.4X") % (self.appjump,))  #Userdata
        s.append(_("TIMEOUT   : %d") % (self.timeout,))    #Userdata
        return '\n'.join(s)
        
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

        self.setPassword("")
        self.one_wire = False
        self.timeout_reset = 100 #ms
        self.device_info = DeviceInfo()
        
        #Timeout for sendind 10 characters 
        self.serial.timeout = 100.0 / serial.baudrate
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
        """Turn on other line than reset line to log 0. The output
        of the pin will be cca +12V which can be use for power RS232 convertor
        """
        if self.reset_line == TSBLoader.DTR:
            self.serial.setRTS(0)
        else:
            self.serial.setDTR(0)
        self.sleep(100)

    def resetMCU(self):
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
        self.waitRespond( TSB_CONFIRM ) 

    def activateTSB(self):
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
        opcodes = [s[i]+s[i+1] for i in xrange(0, len(s), 2)]
        return '\xE8\x95' in opcodes
    
    def flashRead(self):
        if self.state <> TSBLoader.STATE_ACTIVE:
            self.activateTSB()

        flashdata = []
        self.sendCommand("f")

        addr = 0
        rx = "init"
        while (rx <> '') and (addr < self.device_info.appflash):
            self.sendCommand(TSB_CONFIRM)
            rx = self.read(self.device_info.pagesize)
            
            if len(rx) <> self.device_info.pagesize:
                raise TSBException(_("Read flash memory page error."))
    
            addr += len(rx)
            self.log(_("Flash read %.4X") % addr)
            flashdata.append(rx)
        
        if addr < self.device_info.appflash:
            raise TSBException(_("Read Error: other memory page expected."))

        self.waitRespond( TSB_CONFIRM )        
        flashdata = ''.join(flashdata)
        flashdata = flashdata.rstrip("\xFF") #Remove empty data
        return flashdata


    def flashWrite(self, data):
        pagesize = self.device_info.pagesize
        
        #Pad data to all page
        round_data = ( (len(data)-1) / pagesize+1 ) * pagesize
        round_data = min(0, round_data)
        data = data.ljust(round_data, '\xFF')
        
        if len(data) > self.device_info.appflash:
            raise TSBException(_("Error: Not enough space."))
        
        self.sendCommand("F")
        # We must wait than FLASH memory will be erased
        pages_count = self.device_info.appflash / pagesize
        self.waitRespond( TSB_REQUEST, FLASH_PAGEWRITE_TIMEOUT*pages_count) 

        pagenum = 0
        while (pagenum * pagesize) < len(data):
            pagedata = data[pagenum*pagesize : (pagenum+1)*pagesize]
            self.sendCommand(TSB_CONFIRM)
            self.sendCommand(pagedata)
            self.log(_("Flash write %.4X") % (pagenum*pagesize,))
            
            #From datasheet the maximum time for write one page is 4.5ms and
            #minimal time is 3.7 ms. 
            #Function read has timeout only for receive cca 10 characters
            #this is 100ms for 9600 bps
            rx = self.read(1, FLASH_PAGEWRITE_TIMEOUT)   #Wait up to 5ms, read 1 byte
            pagenum += 1
            
            if rx == TSB_CONFIRM:
                raise TSBException(_("Error: end of appflash reached or verifying error"))
            elif rx <> TSB_REQUEST:
                raise TSBException(_("FLASH Write: Undefined error."))

        self.sendCommand(TSB_REQUEST)
        self.waitRespond(TSB_CONFIRM)

    def flashErase(self):
        self.flashWrite('')

    def eepromWrite(self, data):
        pagesize = self.device_info.pagesize
        data = data.ljust(self.device_info.eepromsize, '\xFF')
        
        if len(data) > self.device_info.eepromsize:
            raise TSBException(_("Error: EEPROM not enough space."))
        
        self.sendCommand("E")
        # We must wait than FLASH memory will be erased
        pages_count = self.device_info.eepromsize / pagesize
        self.waitRespond( TSB_REQUEST, FLASH_PAGEWRITE_TIMEOUT*pages_count) 

        pagenum = 0
        while (pagenum * pagesize) < len(data):
            pagedata = data[pagenum*pagesize : (pagenum+1)*pagesize]
            self.sendCommand(TSB_CONFIRM)
            self.sendCommand(pagedata)
            self.log(_("EEPROM write %.4X") % (pagenum*pagesize,))
            
            #From datasheet the maximum time for write one page is 4.5ms and
            #minimal time is 3.7 ms. 
            #Function read has timeout only for receive cca 10 characters
            #this is 100ms for 9600 bps
            rx = self.read(1, FLASH_PAGEWRITE_TIMEOUT)   #Wait up to 5ms, read 1 byte
            pagenum += 1
            
            if rx == TSB_CONFIRM:
                raise TSBException(_("Error: end of eeprom reached or verifying error"))
            elif rx <> TSB_REQUEST:
                raise TSBException(_("EEPROM Write: Undefined error."))

        self.sendCommand(TSB_REQUEST)
        self.waitRespond(TSB_CONFIRM) 


    def eepromErase(self):
        self.eepromWrite('')
        
    def eepromRead(self):
        eepromdata = []
        self.sendCommand("e")

        addr = 0
        rx = "init"
        while (rx <> '') and (addr < self.device_info.eepromsize):
            self.sendCommand(TSB_CONFIRM)
            rx = self.read(self.device_info.pagesize)
            
            if len(rx) <> self.device_info.pagesize:
                raise TSBException(_("Read EEPROM memory page error."))
    
            addr += len(rx)
            self.log(_("EEPROM read %.4X") % addr)
            eepromdata.append(rx)
        
        if addr < self.device_info.eepromsize:
            raise TSBException(_("Read Error: other EEPROM page expected."))
        
        self.sendCommand(TSB_REQUEST)
        self.waitRespond(TSB_CONFIRM)      
        eepromdata = ''.join(eepromdata)
        eepromdata = eepromdata.rstrip("\xFF") #Remove empty data
        return eepromdata
        
    
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
        self.resetMCU()
        self.serial.close()
        self.state = TSBLoader.STATE_CLOSE
    

AVR_SIG2NAME= {
    (0x1E, 0x90, 0x01) : ('1200      ', '1200            '),
    (0x1E, 0x91, 0x01) : ('2313      ', '2313            '),
    (0x1E, 0x91, 0x02) : ('2323      ', '2323            '),
    (0x1E, 0x91, 0x03) : ('2343      ', '2343            '),
    (0x1E, 0x92, 0x01) : ('4414      ', '4414            '),
    (0x1E, 0x92, 0x03) : ('4433      ', '4433            '),
    (0x1E, 0x93, 0x03) : ('4434      ', '4434            '),
    (0x1E, 0x93, 0x01) : ('8515      ', '8515            '),
    (0x1E, 0x97, 0x03) : ('m1280     ', 'ATmega1280      '),
    (0x1E, 0x97, 0x04) : ('m1281     ', 'ATmega1281      '),
    (0x1E, 0x97, 0x06) : ('m1284     ', 'ATmega1284      '),
    (0x1E, 0x97, 0x05) : ('m1284P    ', 'ATmega1284P     '),
    (0x1E, 0xA7, 0x03) : ('m1284RFR2 ', 'ATmega1284RFR2  '),
    (0x1E, 0x97, 0x02) : ('m128A     ', 'ATmega128       '),
    (0x1E, 0xA7, 0x01) : ('m128RFA1  ', 'ATmega128RFA1   '),
    (0x1E, 0xA7, 0x02) : ('m128RFR2  ', 'ATmega128RFR2   '),
    (0x1E, 0x94, 0x04) : ('m162      ', 'ATmega162       '),
    (0x1E, 0x94, 0x0F) : ('m164A     ', 'ATmega164       '),
    (0x1E, 0x94, 0x0A) : ('m164PA    ', 'ATmega164P      '),
    (0x1E, 0x94, 0x10) : ('m165A     ', 'ATmega165       '),
    (0x1E, 0x94, 0x07) : ('m165PA    ', 'ATmega165P      '),
    (0x1E, 0x94, 0x06) : ('m168A     ', 'ATmega168       '),
    (0x1E, 0x94, 0x0B) : ('m168PA    ', 'ATmega168P      '),
    (0x1E, 0x94, 0x11) : ('m169A     ', 'ATmega169       '),
    (0x1E, 0x94, 0x05) : ('m169PA    ', 'ATmega169P      '),
    (0x1E, 0x94, 0x03) : ('m16A      ', 'ATmega16        '),
    (0x1E, 0x94, 0x0C) : ('m16HVA    ', 'ATmega16HV      '),
    (0x1E, 0x94, 0x0D) : ('m16HVB    ', 'ATmega16HVB     '),
    (0x1E, 0x94, 0x84) : ('m16M1     ', 'ATmega16M1      '),
    (0x1E, 0x94, 0x89) : ('m16U2     ', 'ATmega16U2      '),
    (0x1E, 0x94, 0x88) : ('m16U4     ', 'ATmega16U4      '),
    (0x1E, 0x98, 0x01) : ('m2560     ', 'ATmega2560      '),
    (0x1E, 0x98, 0x02) : ('m2561     ', 'ATmega2561      '),
    (0x1E, 0xA8, 0x03) : ('m2564RFR2 ', 'ATmega2564RFR2  '),
    (0x1E, 0xA8, 0x02) : ('m256RFR2  ', 'ATmega256RFR2   '),
    (0x1E, 0x95, 0x15) : ('m324A     ', 'ATmega324       '),
    (0x1E, 0x95, 0x11) : ('m324PA    ', 'ATmega324P      '),
    (0x1E, 0x95, 0x08) : ('m324P     ', 'ATmega324P      '),
    (0x1E, 0x95, 0x0E) : ('m3250A    ', 'ATmega3250      '),
    (0x1E, 0x95, 0x06) : ('m3250     ', 'ATmega3250      '),
    (0x1E, 0x95, 0x05) : ('m325A     ', 'ATmega325       '),
    (0x1E, 0x95, 0x0D) : ('m325P     ', 'ATmega325P      '),
    (0x1E, 0x95, 0x14) : ('m328      ', 'ATmega328       '),
    (0x1E, 0x95, 0x0F) : ('m328P     ', 'ATmega328P      '),
    (0x1E, 0x95, 0x0C) : ('m3290A    ', 'ATmega3290      '),
    (0x1E, 0x95, 0x04) : ('m3290     ', 'ATmega3290      '),
    (0x1E, 0x95, 0x03) : ('m329A     ', 'ATmega329       '),
    (0x1E, 0x95, 0x0B) : ('m329PA    ', 'ATmega329P      '),
    (0x1E, 0x95, 0x02) : ('m32A      ', 'ATmega32        '),
    (0x1E, 0x95, 0x86) : ('m32C1     ', 'ATmega32C1      '),
    (0x1E, 0x95, 0x10) : ('m32HVB    ', 'ATmega32HVB     '),
    (0x1E, 0x95, 0x84) : ('m32M1     ', 'ATmega32M1      '),
    (0x1E, 0x95, 0x8A) : ('m32U2     ', 'ATmega32U2      '),
    (0x1E, 0x95, 0x87) : ('m32U4     ', 'ATmega32U4      '),
    (0x1E, 0x95, 0x07) : ('m406      ', 'ATmega406       '),
    (0x1E, 0x92, 0x05) : ('m48A      ', 'ATmega48        '),
    (0x1E, 0x92, 0x0A) : ('m48PA     ', 'ATmega48P       '),
    (0x1E, 0x96, 0x08) : ('m640      ', 'ATmega640       '),
    (0x1E, 0x96, 0x09) : ('m644A     ', 'ATmega644       '),
    (0x1E, 0x96, 0x0A) : ('m644PA    ', 'ATmega644P      '),
    (0x1E, 0xA6, 0x03) : ('m644RFR2  ', 'ATmega644RFR2   '),
    (0x1E, 0x96, 0x06) : ('m6450A    ', 'ATmega6450      '),
    (0x1E, 0x96, 0x05) : ('m645A     ', 'ATmega645       '),
    (0x1E, 0x96, 0x04) : ('m6490A    ', 'ATmega6490      '),
    (0x1E, 0x96, 0x03) : ('m649A     ', 'ATmega649       '),
    (0x1E, 0x96, 0x0B) : ('m649P     ', 'ATmega649P      '),
    (0x1E, 0x96, 0x02) : ('m64A      ', 'ATmega64        '),
    (0x1E, 0x96, 0x86) : ('m64C1     ', 'ATmega64C1      '),
    (0x1E, 0x96, 0x10) : ('m64HVE2   ', 'ATmega64HVE2    '),
    (0x1E, 0x96, 0x84) : ('m64M1     ', 'ATmega64M1      '),
    (0x1E, 0xA6, 0x02) : ('m64RFR2   ', 'ATmega64RFR2    '),
    (0x1E, 0x93, 0x06) : ('m8515     ', 'ATmega8515      '),
    (0x1E, 0x93, 0x08) : ('m8535     ', 'ATmega8535      '),
    (0x1E, 0x93, 0x0A) : ('m88A      ', 'ATmega88        '),
    (0x1E, 0x93, 0x0F) : ('m88PA     ', 'ATmega88P       '),
    (0x1E, 0x93, 0x07) : ('m8A       ', 'ATmega8         '),
    (0x1E, 0x93, 0x10) : ('m8HVA     ', 'ATmega8HV       '),
    (0x1E, 0x93, 0x89) : ('m8U2      ', 'ATmega8U2       '),
    (0x1E, 0x90, 0x03) : ('tn10      ', 'ATtiny10        '),
    (0x1E, 0x90, 0x07) : ('tn13A     ', 'ATtiny13        '),
    (0x1E, 0x94, 0x12) : ('tn1634    ', 'ATtiny1634      '),
    (0x1E, 0x94, 0x87) : ('tn167     ', 'ATtiny167       '),
    (0x1E, 0x91, 0x0F) : ('tn20      ', 'ATtiny20        '),
    (0x1E, 0x91, 0x0A) : ('tn2313A   ', 'ATtiny2313      '),
    (0x1E, 0x91, 0x0B) : ('tn24A     ', 'ATtiny24        '),
    (0x1E, 0x91, 0x08) : ('tn25      ', 'ATtiny25        '),
    (0x1E, 0x91, 0x0C) : ('tn261A    ', 'ATtiny261       '),
    (0x1E, 0x91, 0x09) : ('tn26      ', 'ATtiny26        '),
    (0x1E, 0x91, 0x07) : ('tn28      ', 'ATtiny28        '),
    (0x1E, 0x92, 0x0E) : ('tn40      ', 'ATtiny40        '),
    (0x1E, 0x92, 0x0D) : ('tn4313    ', 'ATtiny4313      '),
    (0x1E, 0x92, 0x0C) : ('tn43U     ', 'ATtiny43U       '),
    (0x1E, 0x92, 0x15) : ('tn441     ', 'ATtiny441       '),
    (0x1E, 0x92, 0x07) : ('tn44A     ', 'ATtiny44        '),
    (0x1E, 0x92, 0x06) : ('tn45      ', 'ATtiny45        '),
    (0x1E, 0x92, 0x08) : ('tn461A    ', 'ATtiny461       '),
    (0x1E, 0x92, 0x09) : ('tn48      ', 'ATtiny48        '),
    (0x1E, 0x8F, 0x0A) : ('tn4       ', 'ATtiny4         '),
    (0x1E, 0x8F, 0x09) : ('tn5       ', 'ATtiny5         '),
    (0x1E, 0x93, 0x14) : ('tn828     ', 'ATtiny828       '),
    (0x1E, 0x93, 0x15) : ('tn841     ', 'ATtiny841       '),
    (0x1E, 0x93, 0x0C) : ('tn84A     ', 'ATtiny84        '),
    (0x1E, 0x93, 0x0B) : ('tn85      ', 'ATtiny85        '),
    (0x1E, 0x93, 0x0D) : ('tn861A    ', 'ATtiny861       '),
    (0x1E, 0x93, 0x87) : ('tn87      ', 'ATtiny87        '),
    (0x1E, 0x93, 0x11) : ('tn88      ', 'ATtiny88        '),
    (0x1E, 0x90, 0x08) : ('tn9       ', 'ATtiny9         ')
}




