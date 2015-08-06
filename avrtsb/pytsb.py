#!/usr/bin/python
# -*- coding: UTF-8 -*-

import sys, os
import argparse
import firmware
import textwrap
import re
from intelhex import IntelHex, diff_dumps
from tsbloader import *
from tsb_locale import *


sys.modules.setdefault('avrtsb.firmware', firmware)
stderr = sys.stderr 

class AppException(Exception):
    def __init__(self, message):

        # Call the base class constructor with the parameters it needs
        super(AppException, self).__init__(message)
        
class ConsoleApp():
    def __init__(self):
        self.argParserInit()
        self.tsb = None
    
    def argParserInit(self):
        self.parser = argparse.ArgumentParser(
           description =_("Console Tool for TinySafeBoot, the tiny and safe AVR bootloader."),
           prog="pytsb",
        )
        
        subparsers = self.parser.add_subparsers(dest='subparser_name',
                    help='sub-command help')
        parser_tsb = subparsers.add_parser('tsb', help=_('Connect to bootloader') )
        self.argParserTSBInit(parser_tsb)

        parser_fw = subparsers.add_parser('fw', 
            help=_('Make custom TSB firmware') )
        self.argParserFirmwareInit(parser_fw)


    def argParserTSBInit(self, parser):
        con_group = parser.add_argument_group(_("Connection parameters"))
        con_group.add_argument("devicename", 
            help=_("Device name of genuine or virtual serial port"))

        con_group.add_argument("-b", "--baudrate", default=9600, type=int,
            help=_("Set the baudrate of the serial port. Default 9600 bps"))

        con_group.add_argument("-p", "--password", default="",
            help=_("Password for accessing bootloader"))
        
        con_group.add_argument("--reset-dtr", choices=['0','1'],
            metavar='LEVEL = {0,1}', default="1",
            help=_("Reset MCU with DTR line active in LEVEL. Default: --reset-dtr 1") )

        con_group.add_argument("--reset-rts",  choices=['0','1'],
            metavar='LEVEL = {0,1}',
            help=_('Reset MCU with RTS line active in LEVEL')) 

        parser.add_argument("-i", "--info", action="store_true",
            help=_("Show bootloader and device info"))
            
        #group = parser.add_mutually_exclusive_group()
        tsb_group = parser.add_argument_group(_("TinySafeBoot settings"))
        
        tsb_group.add_argument("--new-password", nargs=1, 
            help=_("Change password for activating TinySafeBoot loader."))
        
        tsb_group.add_argument("--change-timeout", nargs="+", type=int,
            metavar="[TIMEOUT_FACTOR] | [TIMEOUT_MS F_CPU]",
             help=_("Change the time how long time the bootloader will wait for activation before the " +
                    "downloaded firmware is started. The waiting time is given by number " +
                    "in range 8..255 (approx 0.1 up to many seconds). The TIMEOUT_FACTOR can be computed " +
                    "from give time in milliseconds and MCU frequency in MHz or Hz.")
        )

        tsb_group.add_argument("--emergency-erase", action='store_true', 
            help=_("Emergency erase after lost password. Reset the contents of the flash ROM " +
                   "and EEPROM to the value '0xff'. " +
                   "The bootloader is not deleted, only TSB password is reset and TIMEOUT_FACTOR set " +
                   "to maximum value 255. Operation is time demanding from 10 s up to 1 minute. ")
        )

        group = parser.add_argument_group(_('FLASH programming') )
        group.add_argument("-fr", "--flash-read", nargs=1, 
            metavar="FILENAME",
            help=_("Read flash ROM device memory and write to the specified file"))
            
        group.add_argument("-fe", "--flash-erase", action="store_true",
            help=_("This will reset the content of the flash ROM to the value '0xff'"))
            
        group.add_argument("-fw", "--flash-write", nargs=1, 
            metavar="FILENAME",
            help=_("Read the specified file and write it to the flash ROM device memory"))
        
        group.add_argument("-fv", "--flash-verify", nargs="?", default=False,  
            metavar="FILENAME",
            help=_("Read the specified file and compare it with the flash ROM device memory. " +  
                   "When it is used with the option --flash-write than the FILENAME can be omitted." ) 
        ) 

        ee_group = parser.add_argument_group(_('EEPROM programming') )
        ee_group.add_argument("-er", "--eeprom-read", nargs=1, 
            metavar="FILENAME",
            help=_("Read EEPROM device memory and write to the specified file"))

        ee_group.add_argument("-ee", "--eeprom-erase", action="store_true",
            help=_("This will reset the content of the EEPROM to the value '0xff'"))

        ee_group.add_argument("-ew", "--eeprom-write", nargs=1, 
            metavar="FILENAME",
            help=_("Read the specified file and write it to the EEPROM device memory"))

        ee_group.add_argument("-ev", "--eeprom-verify", nargs="?", default=False,  
            metavar="FILENAME",
            help=_("Read the specified file and compare it with EEPROM device memory. " +
                   "When is used with --eeprom-write option, the FILENAME can be omitted.")
        ) 
            
        parser.add_argument("-f", "--force", action="store_true",
            help=_("Force to perform some danger operation: overwrite existing file or write " +
                   "write new bootloader to the device flash ROM.")
        )
        
    def argParserFirmwareInit(self, parser):
        parser.add_argument("-d", "--device", default="", type=str,
            help=_("Type of ATtiny/ATmega device for which the firmware will be made. " +
                   "For the list of all supported devices use --device help" )
            )
        
        parser.add_argument("-p", "--rxtx", default="", type=str,
            help=_("Port definition for serial communication. For example d0d1 means D0=RxD and D1=TxD."))
 
        parser.add_argument("-o", "--output", default="", metavar="FILENAME",
            help=_("Name of output file with generated firmware. File will be Hex (.hex) or Binary (other extension)"))

    def run(self):
        args = self.parser.parse_args()
        self.args = args
        if args.subparser_name == 'tsb':
            self.run_tsb()

        if args.subparser_name == 'fw':
            self.run_fw()
            
    def run_tsb(self):
        args = self.args

        # If there is --flash-verify without filename specified arg.flash_verify==None
        # If there is no option --flash-verify arg.flash_verify==False
        if (args.flash_verify == None) and (args.flash_write == None):
            stderr.write(_("%s: error: argument -fv/--flash-verify: expected 1 argument(s)\n") % (sys.argv[0],))
            stderr.write(_("Argument can be omitted only when is used with option --flash-write\n"))
            return 
        
        #--flash-write FILENAME.HEX --flash-verify
        if args.flash_write and (args.flash_verify == None):
            #argparser returns object list for nargs=1 and simple value for nargs=?
            args.flash_verify = args.flash_write[0]
        
        # If there is --eeprom-verify without filename specified arg.eeprom_verify==None
        # If there is no option --eeprom-verify arg.eeprom_verify==False
        if (args.eeprom_verify == None) and (args.eeprom_write == None):
            stderr.write(_("%s: error: argument -fv/--eeprom-verify: expected 1 argument(s)") % (sys.argv[0],))
            stderr.write(_("Argument can be omitted only when is used with option --eeprom-write"))
            return 

        #--eeprom-write FILENAME.HEX --eeprom-verify
        if args.eeprom_write and (args.eeprom_verify == None):
            #argparser returns object list for nargs=1 and simple value for nargs=?
            args.eeprom_verify = args.eeprom_write[0]
        
        if args.change_timeout and len(args.change_timeout) > 2:
            stderr.write(_("%s: error: argument --change-timeout: expected 1 or 2 argument(s)") % (sys.argv[0],))
            return
        
        #print args
        if not args:
            return
        
        if args.emergency_erase:
            self.emergencyErase()
            
        self.activateTSB()
        if args.info:
            self.showDeviceInfo()

        # Bootloader usersettings
        if args.new_password or args.change_timeout:
            self.changeUserData()
            
        #Flash memory programming
        if args.flash_read:
            self.flashRead()
        
        if args.flash_erase:
            self.flashErase()
        
        if args.flash_write:
            self.flashWrite()
        
        if args.flash_verify:
            self.flashVerify()
        
        #EEPROM Programming
        if args.eeprom_read:
            self.eepromRead()

        if args.eeprom_erase:
            self.eepromErase()
        
        if args.eeprom_write:
            self.eepromWrite()
        
        if args.eeprom_verify:
            self.eepromVerify()

    def run_fw(self):
        args = self.args
        
        try:
            self.fw_db = firmware.FirmwareDB()
        except Exception as e:
            stderr.write( _("Cannot access firmware database.\n"))
            print e.message
            return
    
        if args.device == 'help':
            self.showFWDeviceList()
            return
        
        if args.device == "":
            stderr.write(_("pytsb fw: error: argument -d/--device expected., Use --device help for " +
                     "list of all supported devices.\n"))
            return
        
        if args.rxtx == "":
            stderr.write(_("pytsb fw: error: argument -p/--rxtx expected.\n"))
            return
        
        if not re.match("[a-z][0-7][a-z][0-7]", args.rxtx, re.I):
            stderr.write(( _("pytsb fw: error: argument -p/--rxtx must be in the form d0d1, where "+
                     "D0 = RxD, and D1=TxD.\n")))
            return
        
        if args.output == "":
            args.output = "tsb" + "_" + args.device + "_" + args.rxtx + ".hex"

        if os.path.isfile(args.output):
            stderr.write(_("Output file '%s' already exist, do nothing.\n") % (args.output,))
            return
            
        self.makeFirmware()


    def initTSB(self):
        serial = Serial(self.args.devicename, self.args.baudrate)
        self.tsb = TSBLoader( serial )
        self.tsb.password = self.args.password
        
        if self.args.reset_rts <> None:
            self.tsb.reset_line = TSBLoader.RTS
            self.tsb.reset_active = int(self.args.reset_rts)

        if self.args.reset_dtr <> None:
            self.tsb.reset_line = TSBLoader.DTR
            self.tsb.reset_active = int(self.args.reset_dtr)


    def activateTSB(self):
        self.initTSB()
        self.tsb.setPower()     #Has sence only for self powered convertors
        self.tsb.activateTSB()
    
    def showDeviceInfo(self):
        print
        print self.tsb.device_info.tostr()
        print
        
    def flashRead(self):
        out_filename = self.args.flash_read[0]
        if os.path.exists(out_filename) and (not self.args.force):
            raise AppException(_('Error: output file "%s" already exist. Use --force option or delete the existing file.') % (out_filename,))

        data = self.tsb.flashRead()
        ihex = IntelHex()
        ihex.puts(0, data)
                
        filename, ext = os.path.splitext(out_filename)
        out_format = "bin"
        if ext.upper() == '.HEX':
            out_format = "hex"

        ihex.tofile(out_filename, format=out_format)
    
    def flashVerify(self):
        cmp_filename = self.args.flash_verify
        ihex_cmp = self.readDataFromFile(cmp_filename)
        
        flash_data = self.tsb.flashRead()
        ihex_flash = IntelHex()
        ihex_flash.puts(0, flash_data)
        
        sio = StringIO()
        diff_dumps(ihex_flash, ihex_cmp, tofile=sio, name1=_("Flash ROM device memory"), name2=cmp_filename)
        diff_report = sio.getvalue(False)
        sio.close()
        
        if diff_report.strip() == "":
            print _("Data verification OK")
        else:
            stderr.write(_("Flash ROM device verification error"))
            print diff_report
        
    def flashErase(self):
        self.tsb.flashErase()

    def flashWrite(self):
        ihex = self.readDataFromFile(self.args.flash_write[0])
        data = ihex.tobinstr(0)

        if (self.tsb.device_info.tinymega==0) and self.tsb.check4SPM(data):
            if (not self.args.force):
                raise AppException(_("Warning: firmware includes SPM instruction, which can be dangerous for bootloader.\n"+
                                     "Use --force option if you really wish to write to device flash ROM.")
                      )
            print _("Firmware includes SPM instruction. Continue to write to the device flash ROM --force option is used.")

        self.tsb.flashWrite(data)

    def eepromRead(self):
        filename = self.args.eeprom_read[0]
        if os.path.exists(filename) and (not self.args.force):
            raise AppException(_('Error: output file "%s" already exist. Use --force option or delete the existing file.') % (out_filename,))

        data = self.tsb.eepromRead()
        ihex = IntelHex()
        ihex.puts(0, data)
                
        basename, ext = os.path.splitext(filename)
        out_format = "bin"
        if ext.upper() == '.HEX':
            out_format = "hex"

        ihex.tofile(filename, format=out_format)

            
    def eepromVerify(self):
        cmp_filename = self.args.eeprom_verify
        ihex_cmp = self.readDataFromFile(cmp_filename)

        eeprom_data = self.tsb.eepromRead()
        ihex_eeprom = IntelHex()
        ihex_eeprom.puts(0, eeprom_data)        
        
        sio = StringIO()
        diff_dumps(ihex_eeprom, ihex_cmp, tofile=sio, name1=_("EEPROM device memory"), name2=cmp_filename)
        diff_report = sio.getvalue(False)
        sio.close()
        
        if diff_report.strip() == "":
            print _("Data verification OK")
        else:
            stderr.write(_("EEPROM verification error"))
            print diff_report

            
    def eepromErase(self):        
        self.tsb.eepromErase()
        print _("EEPROM Erase OK")
        

    def eepromWrite(self):
        ihex = self.readDataFromFile(self.args.eeprom_write[0])
        data = ihex.tobinstr(0)
        self.tsb.eepromWrite(data)
        print _("EEPROM Write OK")
        
        
    def readDataFromFile(self, filename):
        """Open file filename (.hex, .bin) and returns IntelHex object
        """
        if not os.path.exists(filename):
            raise AppException(_('Input file "%s" not found.') % (filename,))
        
        basename, ext = os.path.splitext(filename)
        if ext.upper() == '.HEX':
            format = 'hex'
        elif ext.upper() == '.BIN':
            format = 'bin'
        else:
            raise AppException(_("Not supported file format. Only only Intel Hex (.HEX) or\n" +
                                 "raw binary files (.BIN) are supported.")
                  )
        
        
        ih = IntelHex()
        ih.fromfile(filename, format)
        return ih
    

    def changeUserData(self):
        if self.args.new_password:
            self.tsb.device_info.password=self.args.new_password[0]

        if self.args.change_timeout:
            if len(self.args.change_timeout) == 1:
                timeout_factor = self.args.change_timeout[0]
            elif len(self.args.change_timeout) == 2:
                timeout_ms = self.args.change_timeout[0]
                f_cpu = self.args.change_timeout[1]
                #Frequency is given in MHz
                if f_cpu < 100:
                    f_cpu *= 1e6
                
                timeout_factor = int((f_cpu * timeout_ms/1000) / 196600)

            self.tsb.device_info.timeout = timeout_factor
        
        self.tsb.writeUserData()
        print _("Write user data OK")
        print _("Timeout factor %d") % (self.tsb.device_info.timeout,)
        print _("Password: %s") % (self.tsb.device_info.password,)

        
    def emergencyErase(self):
        print _("Emergency erase is takes from 10s up to 1 minute")
        print _("Please be patient")
        print
        self.initTSB()
        self.tsb.setPower()     #Has sence only for self powered convertors
        self.tsb.emergencyErase()

        print _("Ressetting MCU, I try to access TSB without password.")
        self.tsb.activateTSB()  #Reset TSB and try to login to TSB
        self.showDeviceInfo()
        
        
    def showFWDeviceList(self):
        devices = self.fw_db.device_names()
        #devices.sort(lambda a,b:cmp(''.join(a), ''.join(b)))
        names=[]
        for aliases in devices:
            names.extend(aliases)
        names.sort()

        print _("List of all supported devices:")
        for line in textwrap.wrap(", ".join(names)):
            print "  ",line
    
    def makeFirmware(self):
        try:
            firmware = self.fw_db.get_firmware(self.args.device)
        except KeyError:
            stderr.write( _("Sorry firmware is not supported for '%s'\n.") % (self.args.device,))
            self.showFWDeviceList()
            return
        
        try:
            firmware.set_rxtx(self.args.rxtx)
        except ValueError:
            supported_ports = ", ".join(firmware.fw_info.port.keys())
            stderr.write(_("Device '%s' doesn't support ports '%s'\n") % (self.args.device, self.args.rxtx) )
            stderr.write(_("Supported ports are: %s\n") % (supported_ports,))
            return
        
        filename, ext = os.path.splitext(self.args.output)
        out_format = "bin"
        if ext.upper() == '.HEX':
            out_format = "hex"
            
        firmware.tofile(self.args.output, out_format)
        print _("TSB firmware saved to file: '%s'") % (self.args.output,)


    def close(self):
        if self.tsb:
            self.tsb.close()
            self.tsb = None

def main():
    app = ConsoleApp()
    #app.run()
    try:
        #pass
        app.run()
    except Exception as e:
        print e.message
    finally:
        app.close()


if __name__ == "__main__":
    main()
    pass
