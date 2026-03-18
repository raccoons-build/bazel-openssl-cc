# This script reads the OpenSSL meta-build system configuration output
# and converts into constants for the BUILD file.

use strict;

our %unified_info;
our %target;
our %config;
our @disablables;

my %perlasm;

sub normalize_path {
    my ($path) = @_;
    $path =~ s{\\}{/}g;
    return $path;
}

sub get_recursive_srcs_of_one {
    my ($value, %seen, %excludes) = @_;
    my %result;
    if (exists $seen{$value}) {
        return(%result);
    }
    if (exists $excludes{$value}) {
        return(%result);
    }
    $seen{$value} = ();
    my $srcs = $unified_info{sources}->{$value};
    my $deps = $unified_info{depends}->{$value};
    # Add source files (.c, .h, .S, .s, .asm) to the result
    # We want to capture all actual source files in the dependency tree
    if ($value =~ m/\.(c|h|S|s|asm|inc)$/) {
        $result{$value} = ();
    }
    # Also add terminal nodes (files with no sources or deps)
    if (not ($srcs or $deps)) {
        $result{$value} = ();
    }
    foreach my $s (@$srcs) {
        %result = (%result, get_recursive_srcs_of_one($s, %seen));
    }
    foreach my $d (@$deps) {
        %result = (%result, get_recursive_srcs_of_one($d, %seen));
    }
    return(%result);
}

sub get_recursive_defines {
    my ($target, %excludes) = @_;
    my %defines;
    if (exists $excludes{$target}) {
        return %defines;
    }
    my $defs = $unified_info{defines}->{$target};
    foreach my $def (@$defs) {
        $defines{$def} = ();
    }
    foreach my $dep (@{$unified_info{depends}->{$target}}) {
        %defines = (%defines, get_recursive_defines($dep, %excludes));
    }
    return %defines;
}

my %libcrypto_srcs = get_recursive_srcs_of_one("libcrypto");
my %excludes = %libcrypto_srcs;
my %libssl_srcs = get_recursive_srcs_of_one("libssl", (), %excludes);
%excludes = (%excludes, %libssl_srcs);
my %openssl_app_srcs = get_recursive_srcs_of_one("apps/openssl", (), %excludes);

my %libcrypto_defines = get_recursive_defines("libcrypto");
my %libssl_defines = get_recursive_defines("libssl", ("libcrypto", 1));
my %openssl_app_defines = get_recursive_defines("apps/openssl", ("libcrypto", 1, "libssl", 1));

# Collect perlasm generation entries from libcrypto
foreach my $src (keys %libcrypto_srcs) {
    if (exists($unified_info{generate}->{$src})) {
        if (not ($src =~ m/.*\.c$/ or $src =~ m/.*\.h$/ or $src =~ m/^.*\.asn1/ or $src =~ m/^.*\.pm/)) {
            $perlasm{$src} = ${unified_info{generate}->{$src}};
        }
    }
}

# Build data structures for JSON output
my @libcrypto_srcs_list;
foreach (sort keys %libcrypto_srcs) {
    my $src = $_;
    next if exists($unified_info{generate}->{$src});
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        if ($src =~ m/.*\.c$/ or $src =~ m/.*\.S$/ or $src =~ m/.*\.s$/ or $src =~ m/.*\.asm$/) {
            push(@libcrypto_srcs_list, normalize_path($src));
        }
    }
}

my @libssl_srcs_list;
foreach my $src (sort keys %libssl_srcs) {
    next if exists($unified_info{generate}->{$src});
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        if ($src =~ m/.*\.c$/ or $src =~ m/.*\.S$/ or $src =~ m/.*\.s$/ or $src =~ m/.*\.asm$/) {
            push(@libssl_srcs_list, normalize_path($src));
        }
    }
}

my @openssl_app_srcs_list;
foreach my $src (sort keys %openssl_app_srcs) {
    next if exists($unified_info{generate}->{$src});
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        if ($src =~ m/.*\.c$/ or $src =~ m/.*\.S$/ or $src =~ m/.*\.s$/ or $src =~ m/.*\.asm$/) {
            push(@openssl_app_srcs_list, normalize_path($src));
        }
    }
}

# Build perlasm data structures
my @perlasm_gen_commands;

foreach (sort keys %perlasm) {
    my $generation = $perlasm{$_};
    my @cmdlinebits;
    push(@cmdlinebits, $target{perlasm_scheme});
    if (@{$generation}[1,]) {
        push(@cmdlinebits, @{$generation}[1,]);
    }
    my $cmdline = join(" ", @cmdlinebits);
    my $cmd = "\$(PERL) \$(execpath " . normalize_path(@{$generation}[0]) . ") " . $cmdline . " \$(execpath " . normalize_path($_) . ");";
    push(@perlasm_gen_commands, $cmd);
}

# Build defines lists
my @libcrypto_defines_list;
foreach my $def (sort keys %libcrypto_defines) {
    push(@libcrypto_defines_list, "-D" . $def);
}

my @libssl_defines_list;
foreach my $def (sort keys %libssl_defines) {
    push(@libssl_defines_list, "-D" . $def);
}

my @openssl_app_defines_list;
foreach my $def (sort keys %openssl_app_defines) {
    push(@openssl_app_defines_list, "-D" . $def);
}

my @defines;
if (exists $target{defines}) {
    push @defines, @{$target{defines}}
}
if (exists $config{defines}) {
    push @defines, @{$config{defines}}
}
if (exists $config{lib_defines}) {
    push @defines, @{$config{lib_defines}}
}
if (exists $config{openssl_other_defines}) {
    push @defines, @{$config{openssl_other_defines}}
}

my @openssl_defines_list;
foreach (sort @defines) {
    push(@openssl_defines_list, "-D" . $_);
}

# Extract config header template values from configdata
my @config_openssl_sys_defines = @{$config{openssl_sys_defines} // []};
my @config_openssl_api_defines = @{$config{openssl_api_defines} // []};
my @config_openssl_feature_defines = @{$config{openssl_feature_defines} // []};

# Output all data as JSON
use JSON::PP;
my $json = JSON::PP->new->utf8->canonical->pretty;
my %output_data = (
    libcrypto_srcs => \@libcrypto_srcs_list,
    libssl_srcs => \@libssl_srcs_list,
    openssl_app_srcs => \@openssl_app_srcs_list,
    perlasm_gen_commands => \@perlasm_gen_commands,
    libcrypto_defines => \@libcrypto_defines_list,
    libssl_defines => \@libssl_defines_list,
    openssl_app_defines => \@openssl_app_defines_list,
    openssl_defines => \@openssl_defines_list,
    config_b64l => ($config{b64l} ? JSON::PP::true : JSON::PP::false),
    config_b64 => ($config{b64} ? JSON::PP::true : JSON::PP::false),
    config_b32 => ($config{b32} ? JSON::PP::true : JSON::PP::false),
    config_bn_ll => ($config{bn_ll} ? JSON::PP::true : JSON::PP::false),
    config_rc4_int => ($config{rc4_int} // "unsigned int"),
    config_processor => ($config{processor} // ""),
    config_openssl_sys_defines => \@config_openssl_sys_defines,
    config_openssl_api_defines => \@config_openssl_api_defines,
    config_openssl_feature_defines => \@config_openssl_feature_defines,
    disablables => \@disablables,
);
print $json->encode(\%output_data);
