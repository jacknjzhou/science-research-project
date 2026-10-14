package auth

import (
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

type Claims struct {
	UserID        int64    `json:"uid"`
	TenantID      int64    `json:"tenant_id"`
	LegalEntityID int64    `json:"legal_entity_id"`
	SecurityLevel string   `json:"security_level"`
	Roles         []string `json:"roles"`
	jwt.RegisteredClaims
}

func GenToken(secret string, ttlSec int64, c Claims) (string, error) {
	now := time.Now()
	c.RegisteredClaims = jwt.RegisteredClaims{
		ExpiresAt: jwt.NewNumericDate(now.Add(time.Duration(ttlSec) * time.Second)),
		IssuedAt:  jwt.NewNumericDate(now),
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, c)
	return tok.SignedString([]byte(secret))
}

func ParseToken(secret, raw string) (*Claims, error) {
	p, err := jwt.ParseWithClaims(raw, &Claims{}, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("非预期签名算法")
		}
		return []byte(secret), nil
	})
	if err != nil {
		return nil, err
	}
	c, ok := p.Claims.(*Claims)
	if !ok || !p.Valid {
		return nil, errors.New("令牌无效")
	}
	return c, nil
}
