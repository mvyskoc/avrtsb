import os, sys
try:
    from avrtsb import firmware
except ImportError:
    sys.path.append('..')
    from avrtsb import firmware
    
    
import glob
import hashlib
from intelhex import IntelHex
import re
from cStringIO import StringIO
import cPickle as pickle
import gzip


TSB_ASM_FILENAME="tsb_tinymega.asm"
OUT_DIR = "TSBFW"


class ASMParser(dict):
    """
    Read only .EQU, .DEF, .DEVICE definitions from assembler files.
    Does not take into account preprocessor conditional directives
    Example of use:
        info = ASMParser("include/m8Adef.inc")
        print repr(info).replace(',',',\n')
    """
    
    RE_HEXNUMBER = re.compile("0x([0-9a-fA-F]+)")
    RE_NUMBER = re.compile("(\d+)")
    RE_EQU = re.compile("\s*\.EQU\s+(\w+)\s*=\s*(\w+)", re.I)
    RE_DEF = re.compile("\s*\.DEF\s+(\w+)\s*=\s*(\w+)", re.I)
    RE_DEVICE = re.compile("\s*\.device\s+(\w+)", re.I)
    
    def __init__(self, filename):
        super(ASMParser, self).__init__()
        file = open(filename, "r")
        try:
            self.parse_asm(file)
        finally:
            file.close()
    
    def parse_asm(self, file):            
        mcu_info = self
        mcu_info['equ'] = dict()
        mcu_info['def'] = dict()
        
        for line in file:
            equ = self.RE_EQU.match(line)
            if equ:
                key = equ.group(1).upper()
                mcu_info['equ'][key] = self.parse_number(equ.group(2))
                continue
            
            def_ = self.RE_DEF.match(line)
            if def_:
                key = def_.group(1).upper()
                mcu_info['def'][key] = self.parse_number(def_.group(2))
                continue
            
            device = self.RE_DEVICE.match(line)
            if device:
                mcu_info['device'] = device.group(1)


    def parse_number(self, str_number):
        str_number = str_number.strip()
        
        match = self.RE_HEXNUMBER.match(str_number)
        if match:
            return int(match.group(1), 16)

        match = self.RE_NUMBER.match(str_number)
        if match:
            return int(match.group(1))

        return str_number


def compile_asm(asm_filename, out_hex, inc_listdir, mcu_def):
    """
    Parameters:
        asm_filename - assembler source file with TSB firmware
        inc_listdir  - list of dirs for include search path
        mcu_def      - CPU speficifaction include file, for example m8Adef.inc
        out_hex      - output filename in intelhex format
    Return - return code 
    """
    cmd_param = {
            'include_dirs' : " -I ".join(inc_listdir),
            'out_hex'      : out_hex,
            'asm_filename' : asm_filename,
            'mcu_def'      : mcu_def
        }
    
    # cmd = "avrasm2 -fI -i %(mcu_def)s -I %(include_dirs)s -o %(out_hex)s %(asm_filename)s" % cmd_param
    cmd = "wine avrasm2 -fI -i %(mcu_def)s -I %(include_dirs)s -o %(out_hex)s %(asm_filename)s" % cmd_param
    print cmd
    cmd_errcode=os.system(cmd)
    return cmd_errcode

    
def add_firmware(name, hex_filename, mcu_info):
    fw_info = firmware.FirmwareInfo()
    fw_info.devices = [name, mcu_info['device']]
    fw_info.signature = ( mcu_info['equ']['SIGNATURE_000'],
                          mcu_info['equ']['SIGNATURE_001'],
                          mcu_info['equ']['SIGNATURE_002']
                        )
    
    for key in mcu_info['equ']:
        if re.match("PIN\w$", key, re.I):
            port_name = key.split("PIN")[1]
            if mcu_info['equ'].has_key("PORT"+port_name) and \
               mcu_info['equ'].has_key("DDR"+port_name):
                   fw_info.pin[port_name] = mcu_info['equ']["PIN"+port_name]
                   fw_info.port[port_name] = mcu_info['equ']["PORT"+port_name]
                   fw_info.ddr[port_name] = mcu_info['equ']["DDR"+port_name]
    
    fw_db.add_firmware(hex_filename, fw_info)
    
def compile_all(mcudef_dir, out_dir):
    """
    Parameters:
        mcudef_dir     - directory with definition file for all CPU (*def.inc)
        out_dir        - output directory with compiled firmwares
    """
    inc_listdir = [mcudef_dir]
    out_dir = OUT_DIR
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    if os.path.isfile(TSB_ASM_FILENAME):
        tsb_asm = TSB_ASM_FILENAME
    else:
        tsb_asm = os.path.join( os.path.dirname(__file__), TSB_ASM_FILENAME )

    if not os.path.isfile(tsb_asm):
        print "Assembler source file '%s' with TSB firmware not found" % (tsb_asm,)
        sys.exit(1)

    fails = []
    for mcudef in glob.glob( os.path.join(mcudef_dir, "*def.inc") ):
        mcudef_dir, mcudef_file = os.path.split(mcudef)
        mcudef_base, mcudef_ext = os.path.splitext(mcudef_file)

        fw_name = mcudef_base.rsplit('def', 1)[0]
        out_hex = os.path.relpath(os.path.join(out_dir, fw_name + '.hex'))

        errcode = compile_asm(tsb_asm, out_hex, inc_listdir, mcudef)
        if errcode == 0:
            mcu_info = ASMParser(mcudef)
            add_firmware(fw_name, out_hex, mcu_info)
        else:
            fails.append(mcudef_file)

    print "Compilation with following including files finished with error:"
    print "  " + "\n  ".join(fails)
    print
            


fw_db = firmware.FirmwareDB()
fw_db.create_emptydb()
compile_all("include", "tsbfw")
fw_db.save()



    
