package internal

import (
	"encoding/json"
	"net/http/httptest"
	"testing"

	"github.com/eplugger/ark/internal/config"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// Pool==nil：sysadmin 未注册，GET /admin/users 落 passthrough（契约已定义），应 code=0、HTTP 200。
func TestBuild_SysadminFallsBackToPassthrough(t *testing.T) {
	gin.SetMode(gin.TestMode)
	l := zap.NewNop()
	cfg := &config.Config{Env: "test", JWTSecret: "s3cr3t", JWTTTLSec: 3600, DesignDir: "../../design"}
	// go test ./internal/ 的工作目录 = backend-go/internal，Casbin 文件相对该目录为 platform/auth/*。
	enf, err := auth.NewEnforcer("platform/auth/model.conf", "platform/auth/policy.csv")
	if err != nil {
		t.Fatal(err)
	}
	spec, err := oapi.LoadDir("../../design")
	if err != nil {
		t.Fatal(err)
	}
	e := Build(RouterDeps{Logger: l, Cfg: cfg, Enforcer: enf, Spec: spec}) // Pool 缺省 nil
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/admin/users", nil))
	if w.Code != 200 {
		t.Fatalf("passthrough 应 200，实得 %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Code int `json:"code"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if env.Code != 0 {
		t.Fatalf("passthrough 包络 code 应为 0: %+v", env)
	}
}
