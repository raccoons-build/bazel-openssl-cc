def get_repo_name():
    return Label("//:BUILD.bazel").workspace_name

# Function to convert a .c file name to a .h file name
def convert_c_to_h(c_file_name):
    if c_file_name.endswith(".c"):
        # Replace .c with .h
        h_file_name = c_file_name[:-2] + ".h"
        return h_file_name
    else:
        # Return the same name if it's not a .c file
        return c_file_name
