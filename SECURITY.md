# Security policy

## Reporting a vulnerability

Please report security issues privately via GitHub's "Report a vulnerability" button on the
Security tab, rather than opening a public issue. If that button is not available, open an issue
titled "security contact request" with no details in it, and we will arrange a private channel.

## Scope

DIAspeXtract is a batch command-line tool. It reads instrument data and writes mzML or mzPeak; it opens no
sockets, runs no server, and requires no credentials. The realistic security surface is therefore
**untrusted input files**: a malformed or hostile Bruker `.d`, `.mzML` or `.mzpeak` reaching the
parser. Reports of crashes, out-of-bounds reads or unbounded allocation triggered by an input file
are in scope and welcome.

Before the reader runs, the tool checks a `.d` itself: that it is diaPASEF, that every frame lies inside
`analysis.tdf_bin`, that no frame claims more points than the file can hold, and that the calibration tables hold
numbers. Most parsing is still done by OpenMS and by the vendor libraries. If the flaw is there, we will help route it
upstream.

## Data handling

DIAspeXtract reads local files and writes local files. It does not phone home, collect telemetry, or
transmit anything; it switches OpenMS's update check off whatever the environment says. If you find otherwise, that is a security bug — report it.
