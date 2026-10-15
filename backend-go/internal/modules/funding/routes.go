package funding

import "github.com/gin-gonic/gin"

// Register 把 F 竖切挂到受保护分组（/api/v1 前缀由 router.Build 提供）。
// 分层：/subjects · /budgets[/:id][/lines|/submit|/approve|/adjust] · /budget-lines/:lineId/balance
//
//	/incomes[/:id/claim|/import-bank-flow] · /expenses[/:id][/submit|/approval]
//	/funding/execution · /funding/warnings · /indirect-fees[/calculate] · /expense/ai-invoice-review
func Register(r gin.IRoutes, h *Handler) {
	// F-01 科目字典
	r.GET("/subjects", h.ListSubjects)
	// F-02/03/04 预算
	r.POST("/budgets", h.CreateBudget)
	r.GET("/budgets", h.ListBudgets)
	r.GET("/budgets/:id", h.GetBudget)
	r.GET("/budgets/:id/lines", h.ListBudgetLines)
	r.POST("/budgets/:id/submit", h.SubmitBudget)
	r.POST("/budgets/:id/approve", h.ApproveBudget)
	r.POST("/budgets/:id/adjust", h.AdjustBudget)
	r.GET("/budget-lines/:lineId/balance", h.LineBalance)
	// F-05/06 到款
	r.POST("/incomes", h.CreateIncome)
	r.GET("/incomes", h.ListIncomes)
	r.POST("/incomes/:id/claim", h.ClaimIncome)
	r.POST("/incomes/import-bank-flow", h.ImportBankFlow)
	// F-07/09/10 报销与审批
	r.POST("/expenses", h.CreateExpense)
	r.GET("/expenses", h.ListExpenses)
	r.GET("/expenses/:id", h.GetExpense)
	r.POST("/expenses/:id/submit", h.SubmitExpense)
	r.POST("/expenses/:id/approval", h.ApprovalAction)
	// 执行率 / 预警 / 计提
	r.GET("/funding/execution", h.FundingExecution)
	r.GET("/funding/warnings", h.FundingWarnings)
	r.POST("/indirect-fees/calculate", h.CalculateIndirectFee)
	r.GET("/indirect-fees", h.ListIndirectFees)
	// F-15 AI 审核（仅建议）
	r.POST("/expense/ai-invoice-review", h.AiInvoiceReview)
	// T14 外拨 / 结转 / 预算追加
	r.POST("/outwards", h.CreateOutward)
	r.GET("/outwards", h.ListOutwards)
	r.POST("/outwards/:id/approval", h.OutwardAction)
	r.POST("/carryovers", h.CreateCarryover)
	r.GET("/carryovers", h.ListCarryovers)
	r.POST("/carryovers/:id/approval", h.CarryoverAction)
	r.POST("/budgets/:id/append", h.AppendBudget)
	r.POST("/budgets/:id/append/approve", h.ApproveBudgetAppend)
	// T15 科目树形管理 + 预警配置
	r.GET("/subjects/tree", h.SubjectsTree)
	r.POST("/subjects", h.CreateSubject)
	r.PUT("/subjects/:id", h.UpdateSubject)
	r.DELETE("/subjects/:id", h.DeleteSubject)
	r.GET("/funding/warn-configs", h.ListWarnConfigs)
	r.POST("/funding/warn-configs", h.CreateWarnConfig)
	r.PUT("/funding/warn-configs/:id", h.UpdateWarnConfig)
	r.DELETE("/funding/warn-configs/:id", h.DeleteWarnConfig)
}
