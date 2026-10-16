Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = 'SneerRPA 节点测试台'
$form.Size = New-Object System.Drawing.Size(600, 310)
$form.StartPosition = 'CenterScreen'
$label = New-Object System.Windows.Forms.Label
$label.Text = '输入文本后点击确认；结果可由 RPA 节点读取。'
$label.Location = New-Object System.Drawing.Point(24, 22)
$label.Size = New-Object System.Drawing.Size(540, 30)
$inputBox = New-Object System.Windows.Forms.TextBox
$inputBox.Name = 'InputText'
$inputBox.AccessibleName = '输入内容'
$inputBox.Multiline = $true
$inputBox.AcceptsReturn = $true
$inputBox.Location = New-Object System.Drawing.Point(24, 62)
$inputBox.Size = New-Object System.Drawing.Size(530, 28)
$confirm = New-Object System.Windows.Forms.Button
$confirm.Name = 'ConfirmButton'
$confirm.Text = '确认'
$confirm.AccessibleName = '确认'
$confirm.Location = New-Object System.Drawing.Point(24, 108)
$confirm.Size = New-Object System.Drawing.Size(100, 36)
$outputBox = New-Object System.Windows.Forms.TextBox
$outputBox.Name = 'ResultText'
$outputBox.AccessibleName = '结果内容'
$outputBox.ReadOnly = $true
$outputBox.Location = New-Object System.Drawing.Point(24, 165)
$outputBox.Size = New-Object System.Drawing.Size(530, 28)
$outputBox.Text = '等待确认'
$confirm.Add_Click({ $outputBox.Text = '已确认：' + $inputBox.Text })
$form.Controls.AddRange(@($label, $inputBox, $confirm, $outputBox))
[System.Windows.Forms.Application]::Run($form)
