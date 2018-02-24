#!/usr/bin/python
# -*- coding: UTF-8 -*-

# Work with precompiled TSB firmwares

import os
import hashlib
import re
from intelhex import IntelHex
from cStringIO import StringIO
import cPickle as pickle
import gzip
import warnings
import struct
import math

TSBDB_FILENAME = "tsb_db.pklz"
TSBDB_PATH = os.path.join( os.path.dirname(__file__), TSBDB_FILENAME )

            
class PORTHelper(object):
    def __init__(self, data=None):
        self.data=[]
        if data:
            self.data = data

    def alphabet_index(self, ch):
        return ord(ch.upper())-ord('A')

    def keys(self):
        keys = []
        for i in xrange(len(self.data)):
            if self.data[i]:
                keys.append( chr(ord('A')+i) )
        return keys

    def values(self):
        return self.data
                
    def has_key(self, key):
        idx = self.alphabet_index(key)
        if (idx >= 0) and (idx < len):
            return self.data[idx] <> None
        return False

    def compare(self, register, inc=0):
        if len(self.data) == len(register.data):
            cmp_values = []
            for i in xrange(len(self.data)):
                if type(self.data[i]) <> type(register.data[i]):
                    return False
                
                if (self.data[i] <> None) and \
                   (self.data[i] <> (register.data[i]+inc)):
                    return False
            return True
        return False
        
    def __setitem__(self, key, item):
        idx = self.alphabet_index(key)
        self.data.extend( [None] * (idx - len(self.data)+1) )
        self.data[idx] = int(item)
        
        if self.data[-1] == None:
            self.data.pop()

    def __getitem__(self, key):
        if self.has_key(key):
            return self.data[self.alphabet_index(key)]
        raise KeyError(key)

    def __eq__(self, other):
        return self.data == other.data
                         
           
class FirmwareInfo(object):
    def __init__(self):
        self.devices=[]
        self.signature=(0, 0, 0)
        self.pin=PORTHelper()
        self.ddr=PORTHelper()
        self.port=PORTHelper()
        self.tsb_start=0
        self.tsb_fwconf="" #Configuration data in TSB

    def add_device_names(self, namelist):
        for name  in namelist:
            if name not in self.devices:
                self.devices.append(name)
                        
    def __eq__(self, fw_info):
        if not isinstance(fw_info, FirmwareInfo):
            raise TypeError("Expected FirmwareInfo object, %s given" % (type(fw_info).__name__,) )
        
        return (
              (self.signature == fw_info.signature) and
              (self.pin == fw_info.pin) and
              (self.port == fw_info.port)
            )
    
    def __getstate__(self):
        state = []
        state.append(self.devices)
        state.append(self.signature)
        state.append(self.pin.data)

        # Very probably  is not necessary to save DDR, PORT registers
        ddr = self.ddr.data
        if self.ddr.compare(self.pin, 1):
            ddr = None
        state.append(ddr)
        
        port = self.port.data
        if self.port.compare(self.pin, 2):
            port = None
        state.append(port)
        state.append(self.tsb_start)
        state.append(self.tsb_fwconf)
        return {0 : state}

    def __setstate__(self, state):
        state = state[0]
        self.devices = state.pop(0)
        self.signature = state.pop(0)
        self.pin = PORTHelper(state.pop(0))

        ddr = state.pop(0)
        if ddr == None:
            ddr = [v+1 if v else None for v in self.pin.data]
        self.ddr = PORTHelper(ddr)

        port = state.pop(0)
        if port == None:
            port = [v+2 if v else None for v in self.pin.data]
        self.port = PORTHelper(port)
        self.tsb_start = state.pop(0)
        self.tsb_fwconf = state.pop(0)

class Firmware(object):
    #OP-Codes for working with I/O registry
    #Second byte is in format AAAAAbbb, where b is bit and A I/O register 0-31
    AVR_SBI = 0b10011010
    AVR_CBI = 0b10011000
    AVR_SBIC = 0b10011001
    AVR_SBIS = 0b10011011
    
    AVR_IO_OP = [AVR_SBI, AVR_CBI, AVR_SBIC, AVR_SBIS]
    
    def __init__(self, bindata, fw_info):
        if (len(bindata) % 2) == 1:
            raise ValueError("Odd length of the str argument, even lenght expected.")
        
        self.fw_info = fw_info
        self._bindata = bindata
        #Default values of RxD, TxD for which the firmware is made
        self.rxd = ("B", 0)
        self.txd = ("B", 1)

    
    def tofile(self, filename, format='hex'):
        ihex = self.getihex()
        ihex.tofile(filename, format=format)

    def addTSBInstallerChecksum(self, op_list):
        # TSB Installer checksum is at the end of the first page
        # Program structure:
        # .org 0
        # rjmp 
        # 0xFF, ... 0xFF
        # ...
        # 0xFF, ... 0xFF
        # rjmp
        # Checksum 2 bytes

        try:
            i = 1
            while (i < 128) and (op_list[i] == "\xFF\xFF"):
                i += 1
        except ValueError, IndexError:
            # No change, no TSB Installer
            return op_list

        # NO TSB Firmware Installer
        if (i < 8) or (i > 128):
            return op_list
        
        # Index i point to rjmp before Checksum
        page_size = i+2
        
        checksum = 0
        for ch in op_list[page_size:]:
            checksum += ord(ch[0]) + ord(ch[1])
            checksum &= 0xffff

        #Checksum is counted through full pages - we check If the firmware is
        #is aligned to full pages. If not we fill the rest with 0xff, 0xff values
        aligned_size = int( math.ceil(len(op_list) / page_size) * page_size )
        checksum = checksum + (aligned_size - len(op_list))*(0xff+0xff)
        checksum &= 0xffff
        
        op_list[page_size-1] = struct.pack('>H', checksum)
        return op_list
        
    def set_rxtx(self, rxdtxd):
        ports = "".join(self.fw_info.port.keys())
        fmt = "[%s][0-7][%s][0-7]" % (ports, ports)

        if not re.match(fmt, rxdtxd, re.I):
            raise ValueError("%s: Wrong format or not supported port value" % (rxdtxd,))
        
        self.rxd = (rxdtxd[0].upper(), int(rxdtxd[1]))
        self.txd = (rxdtxd[2].upper(), int(rxdtxd[3]))

    def _str2op(self, binstr):
        opcodes = []
        for i in xrange(0, len(binstr), 2):
            opcodes.append(binstr[i:i+2])
        return opcodes
                    
    def tobinstr(self):
        op_list = self._str2op(self._bindata)
        port = self.fw_info.port
        pin = self.fw_info.pin
        ddr = self.fw_info.ddr
        new_rxtx = {0:self.rxd, 1:self.txd}

        for index, op in enumerate(op_list):
            op_code = ord(op[1])
            if op_code in self.AVR_IO_OP:
                op_bit = ord(op[0]) & 0b00000111
                op_io = (ord(op[0]) & 0b11111000) >> 3
                
                for register in [port, pin, ddr]:
                    if op_io == register['B']:
                        new_op_io = register[new_rxtx[op_bit][0]]
                        new_op_bit = new_rxtx[op_bit][1]
                        op_list[index] = chr( (new_op_io << 3) | new_op_bit)+chr(op_code)
                
        if self.fw_info.tsb_fwconf:
            op_list.extend(["TSB", self.fw_info.tsb_fwconf])

        self.addTSBInstallerChecksum(op_list)
        return ''.join(op_list)
        
    def getihex(self):
        ihex = IntelHex()
        ihex.puts(self.fw_info.tsb_start, self.tobinstr())
        return ihex

    
    
class FirmwareDB(object):
    PICKLE_PROTOCOL=2
    
    def __init__(self, filename=TSBDB_PATH):
        self.db_filename = filename
        if os.path.isfile(self.db_filename):
            with gzip.open(self.db_filename, 'r') as file:
                self.tsbdb = pickle.load(file)
        else:
            warnings.warn("TSB firmware database not found '%s'" % (self.db_filename, ), RuntimeWarning)
            self.create_emptydb()

    def create_emptydb(self):
        self.tsbdb = dict()

    def add_firmware_info(self, fw_md5, fw_info):
        if not isinstance(fw_info, FirmwareInfo):
            raise TypeError("Expected FirmwareInfo object, %s given" % (type(fw_info).__name__,) )
            
        info_added = False
        for db_fw_info in self.tsbdb[fw_md5][1:]:
            if db_fw_info == fw_info:
                info_added = True
                db_fw_info.add_device_names( fw_info.devices )
        
        if not info_added:
            self.tsbdb[fw_md5].append(fw_info)

        
    def add_firmware(self, filename_hex, fw_info):
        ihex = IntelHex(filename_hex)
        # We remove configuration data from TSB firmware (last 16 bytes)
        # beginnin with TSB ...
        fw_data = ihex.tobinstr()
        fw_info.tsb_fwconf = ""

        fw_parts = fw_data.rsplit("TSB", 1)
        if len(fw_parts) == 2:
            fw_data = fw_parts[0]
            fw_info.tsb_fwconf = fw_parts[1]
        
        fw_info.tsb_start = ihex.minaddr()
        fw_md5 = hashlib.md5(fw_data).hexdigest()
        
        if not self.tsbdb.has_key(fw_md5):
            self.tsbdb[fw_md5] = [ fw_data ]
            
        self.add_firmware_info(fw_md5, fw_info)

    def device_names(self):
        """Return list of tuples. Every tuple include device name and its aliases"""
        devices = []
        for fw_rec in self.tsbdb.values():
            for fw_info in fw_rec[1:]:
                devices.append(fw_info.devices)

        return devices

    def device_names2(self):
        """Return list of tuples. Every tuple include device name and its aliases"""
        devices = []
        for fw_rec in self.tsbdb.values():
            temp = []
            for fw_info in fw_rec[1:]:
                temp.extend(fw_info.devices)
            devices.append(temp)

        return devices

    def sig2name(self, signature):
        """Return list of devices names for given signature.
           Every device should have at least 2 names short name and long name
        """
        signature = tuple(signature)
        dev_names = []
        for fw_rec in self.tsbdb.values():
            for fw_info in fw_rec[1:]:
                if signature == fw_info.signature:
                    dev_names.extend(fw_info.devices)
        return dev_names
                    
        
    def get_firmware(self, device_name):
        device_name=device_name.lower()
        for fw_rec in self.tsbdb.values():
            for fw_info in fw_rec[1:]:
                device_names = [d.lower() for d in fw_info.devices]
                if device_name in device_names:
                    return Firmware(fw_rec[0], fw_info)

        raise KeyError(device_name)
            

    def save(self):
        with gzip.open(self.db_filename, 'wb') as file:
            pickle.dump(self.tsbdb, file, self.PICKLE_PROTOCOL)
 
