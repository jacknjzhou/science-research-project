package main

import (
	"fmt"
	"os"

	"github.com/eplugger/ark/migrations"
)

func main() {
	d := os.Getenv("DESIGN_DIR")
	if d == "" {
		d = "../../design"
	}
	if err := migrations.WriteFiles(d); err != nil {
		panic(err)
	}
	fmt.Println("生成 migrations/000001_init.{up,down}.sql 完成")
}
