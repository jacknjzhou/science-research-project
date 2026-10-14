package auth

import "github.com/casbin/casbin/v2"

func NewEnforcer(modelPath, policyPath string) (*casbin.Enforcer, error) {
	return casbin.NewEnforcer(modelPath, policyPath)
}
