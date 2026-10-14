package estore

import "testing"

func TestModelsCompile(t *testing.T) {
	_ = Project{}
	_ = MidCheck{}
	_ = ProgressReport{}
	_ = FinalAccept{}
}
