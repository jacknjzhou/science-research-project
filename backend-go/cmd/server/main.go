package main

import (
	"log"

	"github.com/eplugger/ark/internal"
	"go.uber.org/zap"
)

func main() {
	l, _ := zap.NewProduction()
	defer l.Sync()
	e := internal.NewRouter(l)
	if err := e.Run(":8787"); err != nil {
		log.Fatal(err)
	}
}
