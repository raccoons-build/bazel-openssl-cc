import sys
import subprocess
import os

# Access all command-line arguments (including the script name)
all_args = sys.argv

# Access only the arguments (excluding the script name)
args = sys.argv[1:]

if len(args) != 4: 
    raise ValueError("Not enough args. Must be exactly 4.")

binary_invocation = args[0]
src_file = args[1]
out_file = args[2]
assembly_flavor = args[3]

subprocess.check_call([binary_invocation, src_file, assembly_flavor, out_file])

if os.path.exists(out_file):
    raise ValueError(f"{out_file} doesn't exist")
