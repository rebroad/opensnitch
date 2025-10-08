package core

// version related consts
const (
	Name    = "opensnitch-daemon"
	Version = "1.7.3"
	Author  = "Simone 'evilsocket' Margaritelli"
	Website = "https://github.com/evilsocket/opensnitch"
)

// GitCommit is set at compile time via -ldflags
var GitCommit = ""

// GetVersionString returns the version string, including git commit for development builds
func GetVersionString() string {
	if GitCommit != "" {
		return Version + " (git:" + GitCommit + ")"
	}
	return Version
}
