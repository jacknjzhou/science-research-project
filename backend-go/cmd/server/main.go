package main

import (
	"log"
	"strconv"

	"github.com/eplugger/ark/internal"
	"github.com/eplugger/ark/internal/config"
	"go.uber.org/zap"
)

func main() {
	l, _ := zap.NewProduction()
	defer l.Sync()
	cfg := config.Load()
	e := internal.NewRouter(l)
	if err := e.Run(":" + strconv.Itoa(cfg.HTTPPort)); err != nil {
		log.Fatal(err)
	}
}
