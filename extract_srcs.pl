# This script reads the OpenSSL meta-build system configuration output
# and converts into constants for the BUILD file.

use strict;

our %unified_info;
our %target;
our %config;

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
my %openssl_app_srcs;
# On Windows we need to modify the path since the configdata file
# will be using different paths delimitters.
if (@ARGV[0] eq "windows") {
    %openssl_app_srcs = get_recursive_srcs_of_one("apps\\openssl", (), %excludes);
} else {
    %openssl_app_srcs = get_recursive_srcs_of_one("apps/openssl", (), %excludes);
}

my %libcrypto_defines = get_recursive_defines("libcrypto");
my %libssl_defines = get_recursive_defines("libssl", ("libcrypto", 1));
my %openssl_app_defines = get_recursive_defines("apps/openssl", ("libcrypto", 1, "libssl", 1));

# Collect all generated files for libcrypto
my %libcrypto_generated_srcs;
my %libcrypto_generated_hdrs;
foreach my $src (keys %libcrypto_srcs) {
    if (exists($unified_info{generate}->{$src})) {
        if ($src =~ m/.*\.c$/) {
            $libcrypto_generated_srcs{$src} = ();
        } elsif ($src =~ m/.*\.h$/) {
            $libcrypto_generated_hdrs{$src} = ();
        } elsif (not ($src =~ m/^.*\.asn1/ or $src =~ m/^.*\.pm/)) {
            $perlasm{$src} = ${unified_info{generate}->{$src}};
        }
    }
}

# Build data structures for JSON output
my @libcrypto_srcs_list;
my @libcrypto_generated_srcs_list;
my @libcrypto_hdrs_list;
my @libcrypto_generated_hdrs_list;

# Separate LIBCRYPTO into sources (.c) and headers (.h)
foreach (sort keys %libcrypto_srcs) {
    my $src = $_;
    # Skip generated files - they'll be added separately
    if (exists($unified_info{generate}->{$src}) and ($src =~ m/.*\.c$/ or $src =~ m/.*\.h$/)) {
        next;
    }
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        if ($src =~ m/.*\.c$/ or $src =~ m/.*\.S$/ or $src =~ m/.*\.s$/ or $src =~ m/.*\.asm$/) {
            push(@libcrypto_srcs_list, normalize_path($src));
        }
    }
}
# Add generated .c files
foreach (sort keys %libcrypto_generated_srcs) {
    push(@libcrypto_generated_srcs_list, normalize_path($_));
}

foreach (sort keys %libcrypto_srcs) {
    my $src = $_;
    # Skip generated files - they'll be added separately
    if (exists($unified_info{generate}->{$src}) and ($src =~ m/.*\.c$/ or $src =~ m/.*\.h$/)) {
        next;
    }
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        if ($src =~ m/.*\.h$/ or $src =~ m/.*\.inc$/) {
            push(@libcrypto_hdrs_list, normalize_path($src));
        }
    }
}
# Add generated .h files
foreach (sort keys %libcrypto_generated_hdrs) {
    push(@libcrypto_generated_hdrs_list, normalize_path($_));
}

# Collect all generated files for libssl
my %libssl_generated_srcs;
my %libssl_generated_hdrs;
foreach my $src (keys %libssl_srcs) {
    if (exists($unified_info{generate}->{$src})) {
        if ($src =~ m/.*\.c$/) {
            $libssl_generated_srcs{$src} = ();
        } elsif ($src =~ m/.*\.h$/) {
            $libssl_generated_hdrs{$src} = ();
        }
    }
}

# Build data structures for JSON output
my @libssl_srcs_list;
my @libssl_generated_srcs_list;
my @libssl_hdrs_list;
my @libssl_generated_hdrs_list;

# Separate LIBSSL into sources (.c) and headers (.h)
foreach my $src (sort keys %libssl_srcs) {
    # Skip generated files - they'll be added separately
    if (exists($unified_info{generate}->{$src}) and ($src =~ m/.*\.c$/ or $src =~ m/.*\.h$/)) {
        next;
    }
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        if ($src =~ m/.*\.c$/ or $src =~ m/.*\.S$/ or $src =~ m/.*\.s$/ or $src =~ m/.*\.asm$/) {
            push(@libssl_srcs_list, normalize_path($src));
        }
    }
}
# Add generated .c files
foreach (sort keys %libssl_generated_srcs) {
    push(@libssl_generated_srcs_list, normalize_path($_));
}

foreach my $src (sort keys %libssl_srcs) {
    # Skip generated files - they'll be added separately
    if (exists($unified_info{generate}->{$src}) and ($src =~ m/.*\.c$/ or $src =~ m/.*\.h$/)) {
        next;
    }
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        if ($src =~ m/.*\.h$/ or $src =~ m/.*\.inc$/) {
            push(@libssl_hdrs_list, normalize_path($src));
        }
    }
}
# Add generated .h files
foreach (sort keys %libssl_generated_hdrs) {
    push(@libssl_generated_hdrs_list, normalize_path($_));
}

# Collect all generated files for openssl_app
my %openssl_app_generated_srcs;
my %openssl_app_generated_hdrs;
foreach my $src (keys %openssl_app_srcs) {
    if (exists($unified_info{generate}->{$src})) {
        if ($src =~ m/.*\.c$/) {
            $openssl_app_generated_srcs{$src} = ();
        } elsif ($src =~ m/.*\.h$/) {
            $openssl_app_generated_hdrs{$src} = ();
        }
    }
}

# Build data structures for JSON output
my @openssl_app_srcs_list;
my @openssl_app_generated_srcs_list;
my @openssl_app_hdrs_list;
my @openssl_app_generated_hdrs_list;

# Separate OPENSSL_APP into sources (.c) and headers (.h)
foreach my $src (sort keys %openssl_app_srcs) {
    # Skip generated files - they'll be added separately
    if (exists($unified_info{generate}->{$src}) and ($src =~ m/.*\.c$/ or $src =~ m/.*\.h$/)) {
        next;
    }
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        if ($src =~ m/.*\.c$/ or $src =~ m/.*\.S$/ or $src =~ m/.*\.s$/ or $src =~ m/.*\.asm$/) {
            push(@openssl_app_srcs_list, normalize_path($src));
        }
    }
}
# Add generated .c files
foreach (sort keys %openssl_app_generated_srcs) {
    push(@openssl_app_generated_srcs_list, normalize_path($_));
}

foreach my $src (sort keys %openssl_app_srcs) {
    # Skip generated files - they'll be added separately
    if (exists($unified_info{generate}->{$src}) and ($src =~ m/.*\.c$/ or $src =~ m/.*\.h$/)) {
        next;
    }
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        if ($src =~ m/.*\.h$/ or $src =~ m/.*\.inc$/) {
            push(@openssl_app_hdrs_list, normalize_path($src));
        }
    }
}
# Add generated .h files
foreach (sort keys %openssl_app_generated_hdrs) {
    push(@openssl_app_generated_hdrs_list, normalize_path($_));
}

# Build perlasm data structures
my @perlasm_outs;
my @perlasm_tools;
my @perlasm_gen_commands;

foreach (sort keys %perlasm) {
    push(@perlasm_outs, $_);
}

foreach (sort values %perlasm) {
    push(@perlasm_tools, @{$_}[0]);
}

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

# Output all data as JSON
use JSON::PP;
my $json = JSON::PP->new->utf8->canonical->pretty;
my %output_data = (
    libcrypto_srcs => \@libcrypto_srcs_list,
    libcrypto_generated_srcs => \@libcrypto_generated_srcs_list,
    libcrypto_hdrs => \@libcrypto_hdrs_list,
    libcrypto_generated_hdrs => \@libcrypto_generated_hdrs_list,
    libssl_srcs => \@libssl_srcs_list,
    libssl_generated_srcs => \@libssl_generated_srcs_list,
    libssl_hdrs => \@libssl_hdrs_list,
    libssl_generated_hdrs => \@libssl_generated_hdrs_list,
    openssl_app_srcs => \@openssl_app_srcs_list,
    openssl_app_generated_srcs => \@openssl_app_generated_srcs_list,
    openssl_app_hdrs => \@openssl_app_hdrs_list,
    openssl_app_generated_hdrs => \@openssl_app_generated_hdrs_list,
    perlasm_outs => \@perlasm_outs,
    perlasm_tools => \@perlasm_tools,
    perlasm_gen_commands => \@perlasm_gen_commands,
    libcrypto_defines => \@libcrypto_defines_list,
    libssl_defines => \@libssl_defines_list,
    openssl_app_defines => \@openssl_app_defines_list,
    openssl_defines => \@openssl_defines_list,
);
print $json->encode(\%output_data);
