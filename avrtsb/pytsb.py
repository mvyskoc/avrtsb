#!/usr/bin/python
# -*- coding: UTF-8 -*-

import sys, os
import argparse
import firmware
import textwrap
import re
import locale
import serial
from intelhex import IntelHex, diff_dumps
from tsbloader import *
from tsb_locale import *

try:
    from serial.tools.list_ports import comports
except ImportError:
    comports = None

sys.modules.setdefault('avrtsb.firmware', firmware)
stderr = sys.stderr 

class AppException(Exception):
    def __init__(self, message):

        # Call the base class constructor with the parameters it needs
        super(AppException, self).__init__(message)

class DataFileContainer():
    def __init__(self):
        self.ihex_data = IntelHex()

    def get_first_line(self, filename):
        """Return first non empty line from the file
        """
        with open(filename, 'r') as file:
            for line in file:
                line = line.strip()
                if line:
                    return line

    def is_intelhex(self, filename):
        first_line = self.get_first_line(filename)
        if first_line and re.match(":[0-9A-F]+", first_line):
            return True

        return False

    def get_fileformat(self, filename):
        basename, ext = os.path.splitext(filename)
        if ext.upper() == '.HEX':
            if self.is_intelhex(filename):
                return 'ihex'
            else:
                raise AppException( _("Not supported HEX file format"))
        else:
            if self.is_intelhex(filename):
                return 'ihex'
        
        return 'raw'

    def fromIntelHexObject(self, ihex):
        self.ihex_data = IntelHex(ihex)

    def fromIntelHex(self, filename):
        self.ihex_data = IntelHex()
        self.ihex_data.fromfile(filename, 'hex')

    def fromBinary(self, filename):
        self.ihex_data = IntelHex()
        self.ihex_data.fromfile(filename, 'bin')

    def fromFile(self, filename, format='auto'):
        if not os.path.exists(filename):
            raise AppException(_('Input file "{}" not found.').format(filename))
       
        if format == 'auto':
            format = self.get_fileformat(filename)

        if format == "ihex":
            self.fromIntelHex(filename)
        elif format == "raw":
            self.fromBinary(filename)
        else:
            raise AppException(
                _('"{}" Unsupported input file format').format(format))

    def getIntelHex(self):
        return self.ihex_data

    def toIntelHex(self, filename):
        self.ihex_data.tofile(filename, 'hex')

    def toBinary(self, filename):
        self.ihex_data.tofile(filename, 'bin')

    def checkOutputFileExists(self, filename, overwrite):
        if os.path.exists(filename) and (not overwrite):
            raise AppException(
                _('Error: output file "{}" already exist. '
                  'Use --force option or delete the existing file.'
                 ).format(filename))


    def toFile(self, filename, format='auto', overwrite=False):
        self.checkOutputFileExists(filename, overwrite)

        if format == 'auto':
            basename, ext = os.path.splitext(filename)
            format = 'raw'
            if ext.upper() == '.HEX':
                format = 'ihex'

        if format == 'ihex':
            self.toIntelHex(filename)
        elif format == 'raw':
            self.toBinary(filename)
        else:
            raise AppException(
                _('"{}" Unsupported output file format').format(format))
    

    def toBinStr(self, start=None, end=None):
        return self.ihex_data.tobinstr(start, end)

    def fromBinStr(self, data, addr = 0):
        self.ihex_data.puts(addr, data)

class ConsoleApp():
    def __init__(self):
        self.argParserInit()
        self.tsb = None
    
    def argParserInit(self):
        self.parser = argparse.ArgumentParser(
           formatter_class=argparse.RawDescriptionHelpFormatter,
           description =_("Console Tool for TinySafeBoot, the tiny and safe AVR bootloader.\n" +
                          "----------------------------------------------------------------"),
           epilog = _(
                      "For more information use:\n" +
                      "  %(prog)s tsb --help\n" +
                      "  %(prog)s fw --help\n\n" +
                      
                      "EXAMPLES:\n" +
                      "  Connect to TSB and show bootloader and device info\n"+
                      "    %(prog)s tsb COM1 -i\n\n" +
                      "  Connection to TSB and write new firmware:\n" +
                      "    %(prog)s tsb COM1 -fw my_program.hex -ew my_eeprom.hex\n\n" +
                      
                      "  Get list of all supported devices for making firmware:\n" +
                      "    %(prog)s tsb -d help\n\n"
                      "  Make custom firmware for ATmega8 with serial interface RX=d0, TX=d1\n"+
                      "    %(prog)s fw -d ATmega8 -pd0d1 -o tsb_ATmega8_d0d1.hex\n\n"
                      ),
           prog="pytsb"
        )
        
        subparsers = self.parser.add_subparsers(dest='subparser_name',
                    help='sub-command help')
        self.parser_tsb = subparsers.add_parser('tsb', help=_('Connect to bootloader') )
        self.argParserTSBInit(self.parser_tsb)

        self.parser_fw = subparsers.add_parser('fw', 
            help=_('Make custom TSB firmware') )
        self.argParserFirmwareInit(self.parser_fw)


    def argParserTSBInit(self, parser):
        con_group = parser.add_argument_group(_("Connection parameters"))
        con_group.add_argument("devicename", 
            help=_("Device name of genuine or virtual serial port. Use %(prog)s help for list of available devices"))

        con_group.add_argument("-b", "--baudrate", default='9600', type=str,
            help=_("Set the baudrate of the serial port. Default 9600 bps"))

        con_group.add_argument("-p", "--password", default="",
            help=_("Password for accessing bootloader"))

        con_group.add_argument("-t", "--timeout", type=int, default=200,
            help=_("After MCU reset wait specified time before the " 
                   "TSB activation sequence is sent. "
                   "Suitable value with the respect to TIMEOUT_FACTOR "
                   "must be chosen. Default value is 200 ms")
        )
        
        reset_group = con_group.add_mutually_exclusive_group()
        
        reset_group.add_argument("--reset-dtr", choices=['0','1'],
            metavar='LEVEL = {0,1}', default="1",
            help=_("Reset MCU with DTR line active in LEVEL. Default: --reset-dtr 1") )

        reset_group.add_argument("--reset-rts",  choices=['0','1'],
            metavar='LEVEL = {0,1}',
            help=_('Reset MCU with RTS line active in LEVEL')) 

        reset_group.add_argument(
            "--reset-cmd", default="", type=str, nargs="?", const="TSB", 
            help=_("Send given command for reset MCU, it must be supported by "
                   "the application. The option cannot be used together with "
                   "the RTS/DTR reset."
                  )
        )

        parser.add_argument("-i", "--info", action="store_true",
            help=_("Show bootloader and device info"))
            
        #group = parser.add_mutually_exclusive_group()
        tsb_group = parser.add_argument_group(_("TinySafeBoot settings"))
        
        tsb_group.add_argument("--new-password", nargs=1, 
            help=_("Change password for activating TinySafeBoot loader."))
        
        tsb_group.add_argument("--change-timeout", nargs="+", type=int,
            metavar=("TIMEOUT_FACTOR", "TIMEOUT_MS F_CPU"),
             help=_("Change the time how long time the bootloader will wait for activation before the " +
                    "downloaded firmware is started. The waiting time is given by number " +
                    "in range 8..255 (approx 0.1 up to many seconds). The TIMEOUT_FACTOR can be computed " +
                    "from given time in milliseconds and MCU frequency in MHz or Hz. " +
                    "The delay shall not be shorter than 100ms.")
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

        group.add_argument(
            "-fff", "--flash-file-format", default="auto", type=str,
            metavar="FORMAT",
            help=_("Format of the file to read from or write into the flash. "
                   "Default value is auto. For list of available options "
                   "use -fwf help"))
        
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

        group.add_argument(
            "-eff", "--eeprom-file-format", default="auto", type=str,
            metavar="FORMAT",
            help=_("Format of the file to read from or write into the eeprom "
                   "memory. Default value is auto. For list of available "
                   "options use -ewf help"))

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
        parser.add_argument("-d", "--device", type=str,
            help=_("Type of ATtiny/ATmega device for which the firmware will be made. " +
                   "For the list of all supported devices use --device help" )
            )
        
        parser.add_argument("-p", "--rxtx", type=str,
            help=_("Port definition for serial communication. For example d0d1 means D0=RxD and D1=TxD."))
 
        parser.add_argument("-o", "--output", metavar="FILENAME",
            help=_("Name of output file with generated firmware. File will be Hex (.hex) or Binary (other extension)"))

        parser.add_argument(
            "-fff", "--flash-file-format", default="auto", type=str,
            metavar="FORMAT",
            help=_("Output file format of the generated firmware. Default: auto"))

        parser.add_argument("-f", "--force", action="store_true",
            help=_("Overwrite existing file"))

    def run(self):
        args = self.parser.parse_args()
        self.args = args
        if args.subparser_name == 'tsb':
            self.run_tsb(self.parser_tsb)

        if args.subparser_name == 'fw':
            self.run_fw(self.parser_fw)
            
    def run_tsb(self, parser):
        args = self.args

        if args.devicename == "help":
            self.showPortList()
            return

        if args.baudrate == "help":
            self.showBaudrates()
            return
        
        if (args.flash_file_format == 'help') or (args.eeprom_file_format == 'help'):
            self.showFileFormats()
            return

            
        if not args.baudrate.isdigit():
            stderr.write(_("%s: error: argument -b/--buadrate: invalid int value: '%s'") % (sys.argv[0], args.baudrate,))
            return
        
        args.baudrate = int(args.baudrate)
        
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
        
        if args.change_timeout:
            if len(args.change_timeout) == 2:
                time_ms, f_cpu = args.change_timeout
                if (time_ms < 100) or (time_ms > 10000):
                    stderr.write( _("{}: error: --change-timeout: time delay shall be in the range 100 .. 10000 ms".
                                   format(sys.argv[0]) ))
                    return
                if (f_cpu < 1) or ( (f_cpu > 25) and (f_cpu < 10000) ) or (f_cpu > 25e6):
                    stderr.write(_("{}: error: --change-timeout: MCU frequency must be value in range 1 .. 25 MHz or "
                                   "10000 .. 25000000 Hz".format(sys.argv[0])))
                    return
            elif len(args.change_timeout) > 2:
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

    def run_fw(self, parser):
        args = self.args
        
        try:
            self.fw_db = firmware.FirmwareDB()
        except Exception as e:
            stderr.write( _("Cannot access firmware database.\n"))
            print(e.message)
            return
    
        if args.device == 'help':
            self.showFWDeviceList()
            return

        if args.flash_file_format == 'help':
            self.showFileFormats()
            return

        if not args.device:
            parser.print_usage()
            stderr.write(_("pytsb fw: error: argument -d/--device expected., Use --device help for " +
                     "list of all supported devices.\n"))
            return
        
        if not args.rxtx:
            parser.print_usage()
            stderr.write(_("pytsb fw: error: argument -p/--rxtx expected.\n"))
            return
        
        if not re.match("[a-z][0-7][a-z][0-7]", args.rxtx, re.I):
            stderr.write(( _("pytsb fw: error: argument -p/--rxtx must be in the form d0d1, where "+
                     "D0 = RxD, and D1=TxD.\n")))
            return
        
        if not args.output:
            args.output = "tsb" + "_" + args.device + "_" + args.rxtx + ".hex"

        self.makeFirmware()


    def initTSB(self):
        try:
            serial_port = Serial(self.args.devicename, self.args.baudrate)
        except Exception as e:        
            if self.args.baudrate not in serial.Serial.BAUDRATES:
                print(_("Try to use standard baudrate from the following list:"))
                self.showBaudrates()
            raise AppException(e.strerror)
            
            
            
        self.tsb = TSBLoader( serial_port )
        self.tsb.timeout_reset = self.args.timeout
        self.tsb.password = self.args.password
        self.tsb.reset_cmd = self.args.reset_cmd
        
        if self.args.reset_rts <> None:
            self.tsb.reset_line = TSBLoader.RTS
            self.tsb.reset_active = int(self.args.reset_rts)

        if self.args.reset_dtr <> None:
            self.tsb.reset_line = TSBLoader.DTR
            self.tsb.reset_active = int(self.args.reset_dtr)
        
    def printProgressBar(self, progress):
        if progress.result != None:
            return

        length = 50
        percent = 100 * (progress.iteration / float(progress.total))
        filledLength = int(length * progress.iteration // progress.total)
        bar = '#' * filledLength + '-' * (length - filledLength)
        sys.stdout.write(
            '\r{} |{}| {:.1f}% {}\r'.
            format(_("Progress"), bar, percent, _("Complete")))

        sys.stdout.flush()

        # Print New Line on Complete
        if progress.iteration == progress.total: 
            print('')

    def showPortList(self):
        if comports:
            print(_('List of available ports:'))
            for port, desc, hwid in sorted(comports()):
                print(_('  %-20s %s') % (port, desc.decode(SYS_ENCODING)))

    def showBaudrates(self):
        print(_('List of standard baudrates, not all of them must be supported:'))
        baudrates = [str(bps) for bps in serial.Serial.BAUDRATES]
        for line in textwrap.wrap(", ".join(baudrates)):
            print(line)
   
    def showFileFormats(self):
        print(_("File format can be one of:"))
        print(_("  {:10s} auto detected, only for input files").format("auto"))
        print(_("  {:10s} Intel Hex").format("ihex"))
        print(_("  {:10s} raw binary").format("raw"))

    def activateTSB(self):
        self.initTSB()
        self.tsb.setPower()     # Has sence only for self powered convertors
        self.tsb.activateTSB()
    
    def showDeviceInfo(self):
        print('')
        print(self.tsb.device_info.tostr())
        print('')
        

    def flashReadData(self):
        print('')
        print(_("Read flash program memory:"))
        for progress in self.tsb.flashRead():
            self.printProgressBar(progress)
            last_progress = progress
        print('')
        print(_("Flash read memory OK"))

        return last_progress.result

    def flashRead(self):
        filename = self.args.flash_read[0]
        overwrite = self.args.force

        file_container = DataFileContainer()
        file_container.checkOutputFileExists(filename, overwrite)

        file_container.fromBinStr( self.flashReadData() )
        file_container.toFile(
            filename, self.args.flash_file_format, self.args.force)


    def flashVerify(self):
        cmp_filename = self.args.flash_verify
        file_container = DataFileContainer()
        file_container.fromFile(cmp_filename, 
                                self.args.flash_file_format)
        ihex_cmp = file_container.getIntelHex()
        
        flash_data = self.flashReadData()
        ihex_flash = IntelHex()
        ihex_flash.puts(0, flash_data)
        
        sio = StringIO()
        diff_dumps(ihex_flash, ihex_cmp, tofile=sio, 
                   name1=_l("Flash ROM device memory"), 
                   name2=cmp_filename)
        diff_report = sio.getvalue(False)
        sio.close()
        
        if diff_report.strip() == "":
            print(_("Data verification OK"))
        else:
            stderr.write(_("Flash ROM device verification error\n"))
            print(diff_report)
        
    def flashErase(self):
        print('')
        print(_("Erase flash program memory:"))
        for progress in self.tsb.flashErase():
            self.printProgressBar(progress)

        print('')
        print(_("FLASH Erase OK"))

    def flashWrite(self):
        file_container = DataFileContainer()
        file_container.fromFile(self.args.flash_write[0],
                                self.args.flash_file_format)
        
        data = file_container.toBinStr()
        if (self.tsb.device_info.tinymega==0) and \
                (self.tsb.check4SPM(data)):

            if (not self.args.force):
                raise AppException(
                    _("Warning: firmware includes SPM instruction, "
                      "which can be dangerous for bootloader. "
                      "Use --force option if you really wish to write "
                      "into the device flash ROM."))

            print(_("Firmware includes SPM instruction. "
                    "Continue to write to the device flash ROM "
                    "--force option is used."))

        print('')
        print(_("Write program Flash memory:"))
        for progress in self.tsb.flashWrite(data):
            self.printProgressBar(progress)
        
        print('')
        print(_("FLASH Write OK"))

    def eepromReadData(self):
        print('')
        print(_("Read EEPROM memory:"))
        for progress in self.tsb.eepromRead():
            self.printProgressBar(progress)
            last_progress = progress

        print('')
        print(_("Read EEPROM OK"))

        return last_progress.result

    def eepromRead(self):
        filename = self.args.eeprom_read[0]
        overwrite = self.args.force

        file_container = DataFileContainer()
        file_container.checkOutputFileExists(filename, overwrite)
        file_container.fromBinStr( self.eepromReadData() )
        file_container.toFile(
            filename, self.args.eeprom_file_format, self.args.force)

    def eepromVerify(self):
        cmp_filename = self.args.eeprom_verify
        file_container = DataFileContainer()
        file_container.fromFile(cmp_filename, 
                                self.args.eeprom_file_format)
        ihex_cmp = file_container.getIntelHex()

        eeprom_data = self.eepromReadData()
        ihex_eeprom = IntelHex()
        ihex_eeprom.puts(0, eeprom_data)        
        
        sio = StringIO()
        diff_dumps(ihex_eeprom, ihex_cmp, tofile=sio, name1=_l("EEPROM device memory"), name2=cmp_filename)
        diff_report = sio.getvalue(False)
        sio.close()
        
        if diff_report.strip() == "":
            print(_("Data verification OK"))
        else:
            stderr.write(_("EEPROM verification error\n"))
            print(diff_report)

            
    def eepromErase(self):        
        print('')
        print(_("Erase EEPROM memory:"))
        for progress in self.tsb.eepromErase():
            self.printProgressBar(progress)
        print('')

        print(_("EEPROM Erase OK"))
        

    def eepromWrite(self):
        file_container = DataFileContainer()
        file_container.fromFile(self.args.eeprom_write[0],
                                self.args.eeprom_file_format)

        data = file_container.toBinStr()
        print('')
        print(_("Write EEPROM memory:"))
        for progress in self.tsb.eepromWrite(data):
            self.printProgressBar(progress)
        
        print('')
        print _("EEPROM Write OK")
        
        
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
                timeout_factor = max(1, timeout_factor)

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

        print(_("List of all supported devices:"))
        for line in textwrap.wrap(", ".join(names)):
            print("  ", line)
    
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
        
        filename = self.args.output
        overwrite = self.args.force
        file_container = DataFileContainer()
        file_container.checkOutputFileExists(filename, overwrite)
        file_container.fromIntelHexObject(firmware.getihex())
        file_container.toFile(filename, 
                              self.args.flash_file_format,
                              self.args.force)
        
        print(_("TSB firmware saved into the file: '{}'").format(filename))


    def close(self):
        if self.tsb:
            self.tsb.close()
            self.tsb = None

def main():
    app = ConsoleApp()
    # app.run() 
    try:
        pass
        app.run()
    except Exception as e:
        print e.message
    finally:
        app.close()


if __name__ == "__main__":
    main()
    pass
